"""Laboratorio webhook_delivery: TU ARCHIVO. Edítalo y guarda; la ventana en vivo lo vuelve a ejecutar.

Una plataforma de tiendas envía webhooks (order.created, order.paid, order.fulfilled,
order.refunded) a 20 endpoints de clientes, ~60 eventos por segundo. WORKERS (24) workers de
entrega se reparten el trabajo: un worker libre le pregunta a `Dispatcher.next(now)` qué enviar,
hace el POST, e informa de la respuesta con `Dispatcher.done(ev, status, now)`.

Ahora el despachador es una sola cola para todos, y envía cada evento una vez: un POST que falla
se abandona. Cuando un endpoint está caído, sus eventos se pierden; cuando sus conexiones se
cuelgan, cada POST retiene un worker los 30 s del cliente HTTP, y pronto todos los workers están
atascados ahí.

Haz las etapas en orden, en este archivo:

  Etapa 1  Reintentos: espera como mucho ATTEMPT_TIMEOUT una respuesta, y reintenta cada fallo
           más tarde con backoff exponencial y jitter (`backoff`) en vez de abandonarlo.
  Etapa 2  Una cola por endpoint (`Endpoint`): como mucho MAX_IN_FLIGHT POST a un endpoint, un
           evento por pedido a la vez, el más viejo primero (order.paid nunca antes que
           order.created), y pausa un endpoint tras DISABLE_AFTER fallos seguidos: una prueba cada
           PROBE_EVERY segundos, y todo lo atrasado se reenvía cuando vuelve a responder.

Lo que tienes (mira labs/webhook_delivery/api.py):
  ev.id, ev.endpoint (su número), ev.key (el pedido), ev.seq (1 created, 2 paid, 3 fulfilled,
  4 refunded), ev.type, ev.created, ev.attempts (los cuenta la plataforma: 1 durante el primero)
  ok(status)        True con una respuesta 2xx; status es None cuando no hubo respuesta
  self.give_up(ev)  márcalo como fallido para siempre: nunca se entrega

Compruébalo:  uv run pytest labs/webhook_delivery
Mira una solución (¡después de intentarlo!):  labs/webhook_delivery/es/reference.py
"""

from __future__ import annotations

import heapq  # noqa: F401  (etapa 1: un montículo de reintentos)
import random
from collections import deque
from collections.abc import Callable

from labs.webhook_delivery.api import Event, ok

ATTEMPT_TIMEOUT = 2.0  # segundos que se espera una respuesta: un endpoint sano responde en ~0.1 s
BACKOFF_BASE = 0.5  # segundos: lo más que espera el 1.er reintento; se duplica cada vez
BACKOFF_CAP = 30.0
MAX_IN_FLIGHT = 4  # POST en vuelo a un mismo endpoint, como mucho
DISABLE_AFTER = 5  # fallos seguidos que pausan un endpoint
PROBE_EVERY = 5.0  # segundos entre pruebas mientras un endpoint está pausado
MAX_ATTEMPTS = 6  # intentos antes de abandonar un evento que sigue fallando (veneno)


class Endpoint:
    """Etapa 2. Un endpoint de un cliente: su propia cola, su parte de los workers, su salud.

    Contrato:
      - `queue` guarda sus eventos aún sin entregar, el más viejo primero (el Dispatcher los añade).
      - `pick(now)` devuelve el evento que enviar ahora, o None: nunca más de MAX_IN_FLIGHT POST
        en vuelo a este endpoint, nunca dos eventos de un pedido (`ev.key`) a la vez, y nunca un
        evento mientras otro más viejo de su pedido siga en la cola.
      - `succeeded(ev, now)` y `failed(ev, now)` le cuentan cómo acabó cada POST que eligió.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random(0)
        self.queue: list[Event] = []  # sin entregar aún, el más viejo primero
        self.retry_at: dict[int, float] = {}  # id del evento -> no antes de este momento
        self.sending: set[int] = set()  # claves (pedidos) con un POST en vuelo
        self.failures = 0  # seguidos
        self.parked = False
        self.probe_at = 0.0

    def pick(self, now: float) -> Event | None:
        """Etapa 2. El evento que enviar ahora, o None.

        - None cuando ya hay MAX_IN_FLIGHT claves enviando (este endpoint tiene su parte).
        - Si está pausado: None, salvo que no haya nada en vuelo y now >= probe_at. Entonces una
          prueba: entre el primer evento de cada pedido en la cola, el de menos `attempts` (el
          más viejo de esos), sea cual sea su retry_at. Uno nuevo, para que uno mal formado que
          falla siempre no pueda dejar el endpoint pausado para siempre.
        - Si no, el evento más viejo de `queue` cuyo pedido esté libre: recorre la cola con un
          conjunto de claves bloqueadas (empieza con `self.sending`); salta un evento cuya clave
          esté bloqueada; añade su clave en todo caso (el resto de ese pedido espera detrás);
          devuelve el primero cuyo `retry_at` (0 por defecto) sea <= now.
        - Añade la clave del evento que devuelvas a `self.sending`.
        """
        raise NotImplementedError("PENDIENTE etapa 2: Endpoint.pick(now)")

    def succeeded(self, ev: Event, now: float) -> None:
        """Etapa 2. Entregado: quítalo de `sending`, `queue` y `retry_at`; failures = 0. Si el
        endpoint estaba pausado, vuelve a estar sano: quita la pausa y vacía `retry_at`, para que
        todo lo atrasado se reenvíe ya (en orden, MAX_IN_FLIGHT a la vez)."""
        raise NotImplementedError("PENDIENTE etapa 2: Endpoint.succeeded(ev, now)")

    def failed(self, ev: Event, now: float) -> bool:
        """Etapa 2. El POST falló. Quita su clave de `sending` y cuenta el fallo. Tras
        DISABLE_AFTER seguidos, pausa el endpoint y vuelve a probar en now + PROBE_EVERY. Si no está
        pausado y `ev.attempts >= MAX_ATTEMPTS`, el endpoint funciona pero este evento no (veneno):
        sácalo de la cola y devuelve True (el Dispatcher lo abandona). Si no, reinténtalo más
        tarde, `retry_at[ev.id] = now + backoff(ev.attempts, self.rng)`, y devuelve False."""
        raise NotImplementedError("PENDIENTE etapa 2: Endpoint.failed(ev, now)")


class Dispatcher:
    """Decide qué envían los workers de entrega, y qué pasa tras cada respuesta.

    Contrato:
      - `submit(ev, now)` se llama una vez por cada evento nuevo.
      - `next(now)` lo llama un worker libre: devuelve el evento que hay que enviar ahora, o None
        (vuelve a preguntar enseguida). Cada evento que devuelves se envía una vez, y al acabar se
        llama a `done(ev, status, now)`: status es el código HTTP, o None (sin respuesta en
        `timeout`).
      - `timeout` es cuánto espera un worker una respuesta (None: los 30 s del cliente).
      - Cada evento debe entregarse una vez, tarde o temprano: abandona uno solo si nunca puede
        salir bien.
    """

    timeout: float | None = None  # Etapa 1: ATTEMPT_TIMEOUT

    def __init__(self, give_up: Callable[[Event], None], rng: random.Random | None = None) -> None:
        self.give_up = give_up
        self.rng = rng or random.Random(0)  # para backoff(): las ejecuciones se repiten
        self.queue: deque[Event] = deque()  # una sola cola para todos los endpoints
        self.retries: list[tuple[float, int, Event]] = []  # etapa 1: (cuándo, id, evento), un montículo
        self.endpoints: dict[int, Endpoint] = {}  # etapa 2: número de endpoint -> su Endpoint
        self.turn = 0  # etapa 2: a qué endpoint se pregunta primero (por turnos)

    def submit(self, ev: Event, now: float) -> None:
        # Etapa 2: añádelo mejor a la cola de su endpoint,
        #          self.endpoints.setdefault(ev.endpoint, Endpoint(self.rng)).queue.append(ev)
        #          (crea cada Endpoint una sola vez: setdefault crea uno en cada llamada, así que
        #          comprueba antes).
        self.queue.append(ev)

    def next(self, now: float) -> Event | None:
        # Etapa 1: primero un reintento que ya toque: si self.retries y self.retries[0][0] <= now,
        #          devuelve heapq.heappop(self.retries)[2].
        # Etapa 2: pregunta a los endpoints por turnos, empezando en self.turn: devuelve el primer
        #          evento que te dé un Endpoint.pick(now) (y pasa self.turn más allá de ese endpoint,
        #          para que a cada endpoint le llegue su turno); si no, None.
        return self.queue.popleft() if self.queue else None

    def done(self, ev: Event, status: int | None, now: float) -> None:
        # Etapa 1: ante un fallo, self.retry(ev, now) en vez de abandonarlo.
        # Etapa 2: díselo a su Endpoint: succeeded(ev, now) si ok(status), si no failed(ev, now), y
        #          abandona el evento solo cuando failed() devuelva True (veneno).
        if not ok(status):
            self.give_up(ev)  # un solo envío: un evento que falla se pierde

    def retry(self, ev: Event, now: float) -> None:
        """Etapa 1. Inténtalo otra vez más tarde: mete (now + backoff(ev.attempts, self.rng), ev.id,
        ev) en el montículo self.retries (ev.id deshace empates: los eventos no se comparan)."""
        raise NotImplementedError("PENDIENTE etapa 1: Dispatcher.retry(ev, now)")


def backoff(attempt: int, rng: random.Random | None = None) -> float:
    """Etapa 1. Segundos que esperar tras el intento fallido número `attempt` (1, 2, 3...):
    "jitter completo", una cantidad al azar entre 0 y BACKOFF_BASE duplicado por cada intento
    hecho (0,5, 1, 2, 4... s), como mucho BACKOFF_CAP. Usa `(rng or random).uniform`.

    El jitter importa: cuando un endpoint vuelve, sus reintentos llegan repartidos en vez de todos
    a la vez.

    >>> 0 <= backoff(1, random.Random(1)) <= 0.5
    True
    """
    raise NotImplementedError("PENDIENTE etapa 1: backoff(attempt)")

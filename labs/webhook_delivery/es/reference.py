"""Laboratorio webhook_delivery: una solución que funciona. Léela después de intentar main.py."""

from __future__ import annotations

import random
from collections.abc import Callable

from labs.webhook_delivery.api import Event, ok

ATTEMPT_TIMEOUT = 2.0  # segundos que se espera una respuesta: un destino sano responde en ~0,1 s
BACKOFF_BASE = 0.5  # segundos: lo más que espera el 1.er reintento; se duplica cada vez
BACKOFF_CAP = 30.0
MAX_IN_FLIGHT = 4  # POST en vuelo a un mismo destino, como mucho
DISABLE_AFTER = 5  # fallos seguidos que pausan un destino
PROBE_EVERY = 5.0  # segundos entre pruebas mientras un destino está pausado
MAX_ATTEMPTS = 6  # intentos antes de abandonar un evento que sigue fallando (veneno)


class Endpoint:
    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random(0)
        self.queue: list[Event] = []  # sin entregar aún, el más viejo primero
        self.retry_at: dict[int, float] = {}  # id del evento -> no antes de este momento
        self.sending: set[int] = set()  # claves con un POST en vuelo
        self.failures = 0  # seguidos
        self.parked = False
        self.probe_at = 0.0

    def pick(self, now: float) -> Event | None:
        if len(self.sending) >= MAX_IN_FLIGHT:
            return None  # este destino ya tiene su parte de los workers
        if self.parked:
            if self.sending or now < self.probe_at:
                return None  # pausado: una prueba a la vez, cada PROBE_EVERY segundos
            return self._probe()
        blocked = set(self.sending)
        for ev in self.queue:
            if ev.key in blocked:
                continue  # un evento anterior de este pedido aún no se ha entregado
            blocked.add(ev.key)  # pase lo que pase, el resto de este pedido espera detrás
            if self.retry_at.get(ev.id, 0.0) <= now:
                self.sending.add(ev.key)
                return ev
        return None

    def _probe(self) -> Event | None:
        # El primer evento de cada pedido puede salir; prueba con el menos intentado (uno nuevo), para
        # que un evento mal formado que falla siempre no pueda dejar el destino pausado.
        heads: dict[int, Event] = {}
        for ev in self.queue:
            heads.setdefault(ev.key, ev)
        if not heads:
            return None
        ev = min(heads.values(), key=lambda e: e.attempts)  # el más viejo entre iguales
        self.sending.add(ev.key)
        return ev

    def succeeded(self, ev: Event, now: float) -> None:
        self.sending.discard(ev.key)
        self.queue.remove(ev)
        self.retry_at.pop(ev.id, None)
        self.failures = 0
        if self.parked:  # sano otra vez: reenvía ya lo atrasado, en orden
            self.parked = False
            self.retry_at.clear()

    def failed(self, ev: Event, now: float) -> bool:
        self.sending.discard(ev.key)
        self.failures += 1
        if self.failures >= DISABLE_AFTER:
            self.parked = True
            self.probe_at = now + PROBE_EVERY
        elif ev.attempts >= MAX_ATTEMPTS:  # el destino funciona, este evento no: veneno
            self.queue.remove(ev)
            self.retry_at.pop(ev.id, None)
            return True
        self.retry_at[ev.id] = now + backoff(ev.attempts, self.rng)
        return False


class Dispatcher:
    timeout = ATTEMPT_TIMEOUT

    def __init__(self, give_up: Callable[[Event], None], rng: random.Random | None = None) -> None:
        self.give_up = give_up
        self.rng = rng or random.Random(0)
        self.endpoints: dict[int, Endpoint] = {}
        self.turn = 0  # por turnos: a qué destino se pregunta primero

    def submit(self, ev: Event, now: float) -> None:
        ep = self.endpoints.get(ev.endpoint)
        if ep is None:
            ep = self.endpoints[ev.endpoint] = Endpoint(self.rng)
        ep.queue.append(ev)

    def next(self, now: float) -> Event | None:
        eps = list(self.endpoints.values())
        for k in range(len(eps)):
            ev = eps[(self.turn + k) % len(eps)].pick(now)
            if ev is not None:
                self.turn = (self.turn + k + 1) % len(eps)
                return ev
        return None

    def done(self, ev: Event, status: int | None, now: float) -> None:
        ep = self.endpoints[ev.endpoint]
        if ok(status):
            ep.succeeded(ev, now)
        elif ep.failed(ev, now):
            self.give_up(ev)

    # la cola de reintentos de la etapa 1; la etapa 2 los guarda por destino
    def retry(self, ev: Event, now: float) -> None:
        self.endpoints[ev.endpoint].retry_at[ev.id] = now + backoff(ev.attempts, self.rng)


def backoff(attempt: int, rng: random.Random | None = None) -> float:
    return (rng or random).uniform(0, min(BACKOFF_CAP, BACKOFF_BASE * 2 ** (attempt - 1)))  # jitter completo

"""Laboratorio canary_releases: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los usuarios envían ~200 peticiones/s a cuatro rutas (/home 55%, /search 25%, /cart 15%, /pay 5%).
Un enrutador las reparte entre las instancias que corren la versión activa: ~0.3% de errores, p99
~160 ms.

Cada par de minutos el equipo publica una versión nueva: un DESPLIEGUE. Para cada uno el escenario
crea un `Release()` y llama a `release.decide(metrics)` enseguida y luego cada 5 s. Devuelves la
parte del tráfico que debe recibir la versión nueva, de 0 a 1. El enrutador manda esa parte de las
peticiones (al azar, petición a petición) a instancias con la versión nueva: el CANARIO. El resto va
a la versión activa: la BASE. Devuelve 1.0 y la versión nueva pasa a estar activa en todas partes
(el despliegue termina); devuelve 0.0 y se revierte (el despliegue termina). Ahora mismo `decide`
devuelve 1.0 enseguida: cada usuario recibe cada versión nueva.

La mayoría de las versiones son buenas. Algunas no, como en producción: CAÍDAS EN BUCLE (la mayoría
de las peticiones fallan enseguida: falta un ajuste, una configuración mala), una regresión sutil de
ERRORES (el 0.3% de errores pasa a ~3%), una regresión de LATENCIA (una consulta N+1 nueva: +150-250
ms en un cuarto de las peticiones, y ningún error), o un fallo solo en /PAY (un cambio de redondeo:
falla el 15-30% de los pagos, el 5% del tráfico). Y a veces sale una versión buena mientras una
DEPENDENCIA FALLA A RATOS (la base de datos conmuta, un fallo de DNS): los errores y las respuestas
lentas suben en las dos versiones, y una regla ingenua culpa a la nueva. Una versión mala que llega
al 100% sigue activa hasta que alguien de guardia la revierte a mano, 2 minutos después del
despliegue. El primer despliegue es siempre una regresión de latencia a la 0:20.

Haz las etapas en orden, en este archivo:

  Etapa 1  Un canario con reglas fijas: el 5% del tráfico; revierte si su tasa de errores supera
           ERROR_LIMIT; tras BAKE segundos, a todas partes.
  Etapa 2  Compara el canario con la base en los mismos segundos, en errores Y en respuestas
           lentas, en total y por ruta, con una prueba estadística y un mínimo; sube por STEPS
           (5% -> 25% -> 50% -> 100%) cuando cada etapa ha durado lo suficiente; revierte solo.

Compruébalo:  LABS_LANG=es uv run pytest labs/canary_releases
Mira una solución (¡después de intentarlo!):  labs/canary_releases/es/reference.py
"""

from __future__ import annotations

import math  # noqa: F401  (etapa 2: math.sqrt)
from dataclasses import dataclass

CANARY = 0.05  # etapa 1: la parte del tráfico que recibe el canario
BAKE = 60.0  # etapa 1: segundos en el canario antes de ir a todas partes
ERROR_LIMIT = 0.05  # etapa 1: revierte por encima de esta tasa de errores (holgada, o el ruido revierte versiones buenas)
STEPS = (0.05, 0.25, 0.50, 1.0)  # etapa 2: las partes del tráfico por las que subir, de una en una
STEP_BAKE = 20.0  # etapa 2: segundos que debe durar una etapa antes de la siguiente
MIN_SAMPLES = 200  # etapa 2: peticiones del canario que necesita una etapa antes de la siguiente
MIN_BAD = 5  # etapa 2: nunca culpes al canario por menos respuestas malas que esto
Z_LIMIT = 4.0  # etapa 2: cuántos errores estándar peor es "peor" (estricto: pruebas 10 cosas cada 5 s)


@dataclass(frozen=True, slots=True)
class Counts:
    """Las respuestas de una versión desde que el enrutador cambió el reparto por última vez.

      requests  peticiones respondidas
      errors    de ellas, errores (5xx)
      slow      de ellas, respondidas bien pero en más de 250 ms
    """

    requests: int
    errors: int
    slow: int


@dataclass(frozen=True, slots=True)
class Metrics:
    """Lo que ve `decide`, cada 5 s de un despliegue.

      t          ahora, en segundos
      since      cuándo empezó este despliegue (cuándo se desplegó su versión)
      weight     la parte del tráfico que recibe ahora el canario (0.0 en la primera llamada)
      step_age   segundos desde que el enrutador cambió el reparto por última vez
      canary     los Counts de la versión nueva desde entonces (los mismos segundos que la base)
      baseline   los Counts de la versión activa desde entonces
      endpoints  por ruta ("home", "search", "cart", "pay"): (Counts del canario, Counts de la base)
    """

    t: float
    since: float
    weight: float
    step_age: float
    canary: Counts
    baseline: Counts
    endpoints: dict[str, tuple[Counts, Counts]]


class Release:
    """Publica una versión. El escenario crea un Release por versión.

    Contrato:
      - `decide(m)` se llama al desplegar la versión y luego cada 5 s, hasta que devuelve 1.0 o 0.0.
        Devuelve un float de 0 a 1: la parte del tráfico que recibe la versión nueva hasta la
        siguiente llamada. 1.0 = pasa a estar activa en todas partes (terminado); 0.0 = revertirla
        (terminado); cualquier valor entre medias = un canario de ese tamaño.
      - El enrutador mide cada reparto por separado: cuando tu respuesta cambia la parte, los Counts
        vuelven a empezar desde cero (así el canario y la base siempre se comparan en los mismos
        segundos).
      - Un despliegue que sigue en curso 2 minutos después de desplegarse se anula (se revierte).
    """

    def decide(self, m: Metrics) -> float:
        # Etapa 1: devuelve fixed_canary(m) en su lugar.
        #
        # Etapa 2: devuelve ramp(m) en su lugar.
        return 1.0


def fixed_canary(m: Metrics) -> float:
    """Etapa 1. Un canario con reglas fijas: 0.0 (revertir) cuando el canario ha respondido peticiones
    y su tasa de errores (m.canary.errors / m.canary.requests) supera ERROR_LIMIT; 1.0 (a todas
    partes) cuando el despliegue lleva BAKE segundos (m.t - m.since); si no, CANARY.

    Así empiezan muchos equipos, y detecta las caídas en bucle en segundos, en el 5% de los usuarios.
    Luego mira: la regresión de latencia no tiene errores, así que espera tranquila y llega a todas
    partes. Y un número fijo no distingue una versión mala de un mal momento: cuando una dependencia
    falla a ratos, los errores del canario suben también (y los de la versión activa), y la regla
    revierte una versión buena. Baja el límite y el ruido revierte versiones buenas; súbelo y una
    regresión sutil pasa por debajo.
    """
    raise NotImplementedError("TODO etapa 1: fixed_canary(m)")


def z_score(bad_a: int, n_a: int, bad_b: int, n_b: int) -> float:
    """Etapa 2. Una prueba z de dos proporciones: cuántos errores estándar está la parte mala de a
    (bad_a de n_a) por encima de la parte mala de b. 0.0 cuando algún n es 0, o cuando no hay nada
    malo en absoluto.

        pooled = (bad_a + bad_b) / (n_a + n_b)
        se     = sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
        z      = (bad_a / n_a - bad_b / n_b) / se

    Pista: z_score(30, 1000, 30, 1000) == 0.0; z_score(30, 1000, 3, 1000) es más o menos 4.7.
    """
    raise NotImplementedError("TODO etapa 2: z_score(bad_a, n_a, bad_b, n_b)")


def worse(canary: Counts, baseline: Counts) -> bool:
    """Etapa 2. True cuando el canario es significativamente peor que la base: en errores, o en
    respuestas lentas, tiene al menos MIN_BAD de ellas Y su z_score frente a la base supera Z_LIMIT.

    Frente a la base, no frente a un número fijo: cuando una dependencia falla a ratos, las dos
    versiones empeoran juntas y la prueba no ve diferencia. MIN_BAD evita que un error con mala suerte
    en un canario pequeño parezca 10 veces la base. Z_LIMIT es estricto porque haces esta prueba 10
    veces cada 5 s (errores y lentas, en total y por ruta): con 3 alguna lo cruza por azar de vez en
    cuando, y se revierte una versión buena.

    Pista: for (c, b) in ((canary.errors, baseline.errors), (canary.slow, baseline.slow)): ...
    """
    raise NotImplementedError("TODO etapa 2: worse(canary, baseline)")


def ramp(m: Metrics) -> float:
    """Etapa 2. Un canario por etapas que se revierte solo:

      - 0.0 cuando el canario es worse(m.canary, m.baseline), o peor en una sola ruta
        (m.endpoints da los Counts (canario, base) de cada una): un fallo solo en /pay es el 5% del
        tráfico, demasiado diluido para notarse en el total hasta que buena parte del tráfico lo tiene;
      - STEPS[0] en la primera llamada (m.weight es 0.0);
      - la siguiente parte de STEPS tras m.weight cuando la etapa ha durado STEP_BAKE segundos
        (m.step_age) con al menos MIN_SAMPLES peticiones del canario (muestras suficientes antes de
        decidir);
      - si no, m.weight: espera, y sigue midiendo.

    Pista: min(s for s in STEPS if s > m.weight) es la siguiente etapa.
    """
    raise NotImplementedError("TODO etapa 2: ramp(m)")

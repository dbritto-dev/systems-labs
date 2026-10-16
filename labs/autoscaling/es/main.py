"""Laboratorio autoscaling: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los usuarios envían ~120-230 peticiones/s: el tráfico sigue un día comprimido (mucho a la
1:00, poco a las 6:00), deriva y llega a ráfagas cortas. Un balanceador de carga lo reparte
entre una flota de instancias. Una instancia caliente hace ~20 peticiones/s (2 a la vez,
~100 ms cada una) y pone en cola el resto; un usuario cuya petición espera 2 s se rinde (un
504).

Cada 10 s el escenario llama a tu `Autoscaler.desired(metrics)`: devuelves cuántas
instancias debe tener la flota, y arranca o termina instancias hasta llegar ahí (entre
MIN_INSTANCES y MAX_INSTANCES). Una instancia nueva ARRANCA durante 20-35 s (la pagas, no
sirve nada) y luego sirve mientras SE CALIENTA (cachés vacías, el JIT en frío: 2x más lenta
al principio, caliente a los 20 s). El costo son instancias-segundo: cada instancia que
tienes, arrancando o no. Ahora mismo la flota es fija: `desired` devuelve lo que ya tienes.

De vez en cuando, como en producción: el tráfico da un PICO (un anuncio en la tele, una
publicación viral), BAJA (una región se traslada a otra), la CPU se vuelve RUIDOSA (un
proceso por lotes en las mismas máquinas: la CPU sube, la capacidad no) o un despliegue
gradual reinicia las instancias EN FRÍO. El primer incidente es siempre un pico de 2x a la
0:20.

Haz las etapas en orden, en este archivo:

  Etapa 1  Umbrales de CPU: una instancia más con la CPU sobre 70%, una menos bajo 30%.
  Etapa 2  Seguimiento de objetivo: la flota que necesita el tráfico a TARGET_RPS
           peticiones/s por instancia, en un paso proporcional; reduce solo tras STABILISE
           segundos.

Compruébalo:  LABS_LANG=es uv run pytest labs/autoscaling
Mira una solución (¡después de intentarlo!):  labs/autoscaling/es/reference.py
"""

from __future__ import annotations

import math  # noqa: F401  (etapa 2: math.ceil)
from collections import deque
from dataclasses import dataclass

TARGET_RPS = 10.0  # peticiones/s por instancia a las que apuntar: la mitad de lo que puede una caliente (el margen)
SCALE_OUT_CPU = 0.70  # etapa 1: añade una instancia con la CPU por encima de esto
SCALE_IN_CPU = 0.30  # etapa 1: quita una por debajo de esto
STABILISE = 40.0  # etapa 2: segundos que debe durar una recomendación más baja antes de reducir
MIN_INSTANCES = 2  # el escenario nunca baja de esto ...
MAX_INSTANCES = 40  # ... ni sube de esto, devuelvas lo que devuelvas


@dataclass(frozen=True, slots=True)
class Metrics:
    """Lo que ve el autoescalador cada 10 s (medias de los últimos 10 s).

      t          ahora, en segundos
      instances  cada instancia que pagas: arrancando, calentándose y calientes
      booting    arrancadas, aún sin servir (20-35 s)
      warming    sirviendo, pero aún lentas (cachés vacías, el JIT en frío)
      rps        peticiones/s que enviaron los usuarios (según el balanceador)
      cpu        CPU media de las instancias que sirven, de 0 a 1 (cuenta todo lo que corre
                 en la máquina: un proceso por lotes, un JIT en frío)
      in_flight  peticiones en curso de media por instancia que sirve (en cola o atendiéndose)
    """

    t: float
    instances: int
    booting: int
    warming: int
    rps: float
    cpu: float
    in_flight: float

    @property
    def serving(self) -> int:
        """Instancias que reciben peticiones (calentándose o calientes)."""
        return self.instances - self.booting


class Autoscaler:
    """Decide el tamaño de la flota.

    Contrato:
      - `desired(m)` se llama cada 10 s con las Metrics de los últimos 10 s y devuelve un
        int: cuántas instancias quieres (contando las que ya tienes). El escenario lo
        limita a MIN_INSTANCES..MAX_INSTANCES; si es más de las que tienes arranca el resto
        (que arrancan), si es menos termina las que sobran (primero las que aún arrancan).
      - El escenario crea un Autoscaler por ejecución; guarda en `self` lo que necesites.
    """

    def __init__(self) -> None:
        self.wants: deque[tuple[float, int]] = deque()  # etapa 2: (t, recomendación), los últimos STABILISE s

    def desired(self, m: Metrics) -> int:
        # Etapa 1: devuelve cpu_step(m.cpu, m.instances) en su lugar.
        #
        # Etapa 2: devuelve self.stabilised(m.t, target_tracking(m)) en su lugar.
        return m.instances

    def stabilised(self, t: float, want: int) -> int:
        """Etapa 2. Crece enseguida, reduce despacio: guarda cada recomendación `want` con su
        instante `t` en self.wants, olvida las de hace más de STABILISE segundos y devuelve la
        más alta que quede.

        Así, cuando el tráfico salta creces enseguida (la recomendación nueva es la más alta),
        pero un bajón solo encoge la flota cuando todas las recomendaciones de los últimos
        STABILISE segundos están de acuerdo. Sin esto cada ráfaga añade instancias y el bajón
        siguiente las quita otra vez: oscila (y cada instancia nueva arranca y se calienta en
        frío para nada).

        Pista: añade (t, want); haz popleft mientras self.wants[0][0] <= t - STABILISE;
        devuelve el máximo de las recomendaciones.
        """
        raise NotImplementedError("PENDIENTE etapa 2: Autoscaler.stabilised(t, want)")


def cpu_step(cpu: float, instances: int) -> int:
    """Etapa 1. El tamaño de la flota tras una regla de umbral: instances + 1 si `cpu` está por
    encima de SCALE_OUT_CPU, instances - 1 si está por debajo de SCALE_IN_CPU, si no instances.

    Así empiezan muchos autoescaladores (una alarma de CPU y un paso de uno). Luego mira:
    durante un pico la flota crece una instancia cada 10 s, y cada una arranca durante
    20-35 s, así que siempre va por detrás; las peticiones acaban en timeout. Y la CPU no es el
    tráfico: cuando corre un proceso por lotes en las mismas máquinas, la CPU sube y la regla
    añade instancias que nadie necesita; mientras un despliegue reinicia instancias en frío,
    su CPU también sube.
    """
    raise NotImplementedError("PENDIENTE etapa 1: cpu_step(cpu, instances)")


def target_tracking(m: Metrics) -> int:
    """Etapa 2. Cuántas instancias necesita el tráfico, en un paso proporcional: m.rps entre
    TARGET_RPS, redondeado hacia arriba, y al menos MIN_INSTANCES.

    Sigue la carga (peticiones/s), no la CPU, así que un vecino ruidoso o un JIT en frío no la
    mueven. TARGET_RPS es la mitad de lo que puede una instancia caliente: ese margen absorbe
    las ráfagas, y lo que crece un pico durante los 30-60 s que tardan las instancias nuevas en
    arrancar y calentarse.

    Cuenta el calentamiento: el resultado es la flota entera, con las instancias que arrancan
    y las que se calientan (ya están en `m.instances`, y servirán pronto). NO añadas
    instancias por las que aún no sirven, como en `m.instances + necesarias - m.serving`: cada
    10 s se volverían a pedir las que siguen arrancando, y la flota se pasa de largo.

    Pista: max(MIN_INSTANCES, math.ceil(m.rps / TARGET_RPS)).
    """
    raise NotImplementedError("PENDIENTE etapa 2: target_tracking(m)")

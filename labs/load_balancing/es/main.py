"""Laboratorio load_balancing: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los usuarios envían ~250 peticiones/s. Cada una llega a uno de 4 balanceadores de carga,
y ese balanceador le pregunta a tu `Balancer.pick()` cuál de los 8 servidores la recibe.
Un servidor atiende 4 peticiones a la vez (~40 ms cada una) y pone en cola el resto. Una
petición sin respuesta en 1 s da timeout (el usuario recibe un 504). Ahora mismo cada
balanceador reparte por turnos: servidor 0, 1, 2, ... 7, 0, 1, ... esté como esté cada
servidor.

De vez en cuando un servidor se vuelve lento (un vecino ruidoso, una tormenta de GC, un
disco que falla) o se reemplaza por uno en frío, que va lento hasta que se calienta. Por
turnos le sigue dando 1 de cada 8 peticiones: su cola crece y sus usuarios esperan, hasta
que les salta el timeout.

Lo que sabe un balanceador: `loads`, cuántas peticiones tenía en curso cada servidor (en
cola o atendiéndose), de media en el medio segundo antes de su último informe de carga.
Cada balanceador lee un informe nuevo cada 0.5 s, cada uno en su momento, así que `loads`
puede ir hasta un segundo por detrás: datos viejos.

Haz las etapas en orden, en este archivo:

  Etapa 1  Menos peticiones pendientes: manda cada petición al servidor con menos
           peticiones en curso.
  Etapa 2  Dos opciones al azar: elige dos servidores al azar y manda la petición al
           menos cargado de los dos.

Compruébalo:  LABS_LANG=es uv run pytest labs/load_balancing
Mira una solución (¡después de intentarlo!):  labs/load_balancing/es/reference.py
"""

from __future__ import annotations

import random


class Balancer:
    """Elige un servidor para cada petición, en un balanceador de carga.

    Contrato:
      - `pick(loads)` devuelve el índice (de 0 a servers - 1) del servidor para esta petición.
      - `loads[i]` es cuántas peticiones tenía en curso el servidor i (en cola o
        atendiéndose), de media en los 0.5 s antes del último informe de carga (un float,
        hasta un segundo por detrás). Es una copia: cambiarla no cambia nada.
      - `self.rng` es el generador aleatorio de este balanceador: úsalo (no `random`), para
        que cada ejecución salga igual.

    El escenario crea un Balancer por balanceador de carga (4); no comparten nada.
    """

    def __init__(self, servers: int, rng: random.Random) -> None:
        self.servers = servers
        self.rng = rng
        self.next = 0  # por turnos: el servidor de la siguiente petición

    def pick(self, loads: list[float]) -> int:
        # Etapa 1: devuelve least_outstanding(loads) en su lugar.
        #
        # Etapa 2: devuelve two_choices(loads, self.rng) en su lugar.
        server = self.next
        self.next = (self.next + 1) % self.servers
        return server


def least_outstanding(loads: list[float]) -> int:
    """Etapa 1. El índice del servidor con menos peticiones en curso en `loads`.

    Si hay empate, cualquiera vale (el primero está bien). Pista: min(range(len(loads)),
    key=...) lo encuentra en una línea.

    Luego mira: la cola del servidor lento mantiene baja su parte, pero cada balanceador
    manda TODAS sus peticiones del siguiente medio segundo al único servidor que parecía
    libre en su informe. Si ese es el servidor lento, le cae una ráfaga entera y da timeout.
    (Desempatar al azar no ayuda: las cargas son medias, así que casi siempre hay un único
    mínimo.)
    """
    raise NotImplementedError("PENDIENTE etapa 1: least_outstanding")


def two_choices(loads: list[float], rng: random.Random) -> int:
    """Etapa 2. Elige dos servidores distintos al azar; devuelve el que tenga menos
    peticiones en curso (cualquiera de los dos si empatan).

    Pista: rng.sample(range(len(loads)), 2) da dos índices distintos.

    Por qué gana al menos cargado cuando los informes son viejos: se siguen evitando los
    servidores más ocupados (el más ocupado nunca sale elegido), pero las peticiones se
    reparten entre todos los que no lo están, en vez de caer todas en el que parecía mejor
    hace medio segundo.
    """
    raise NotImplementedError("PENDIENTE etapa 2: two_choices")

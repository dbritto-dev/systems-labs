"""Laboratorio replication_lag: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Una base de datos primaria y 4 réplicas de lectura (r1..r4). Cada escritura se consolida en el
primario y llega a cada réplica 50-200 ms después; a veces mucho después (una réplica se
retrasa, se reinicia o llega un pico de escrituras). Tu `Router` decide adónde va cada lectura.
Ahora mismo manda cada lectura a cualquier réplica que esté en marcha, así que los usuarios no ven
sus propios cambios justo después de hacerlos, y las páginas retroceden en el tiempo cuando una
lectura cae en una réplica retrasada.

Haz las etapas en orden, en este archivo:

  Etapa 1  Lee tus escrituras: guarda la posición en el log (LSN) de la última escritura de
           cada sesión y lee solo de una réplica que ya la haya aplicado; si ninguna, del primario.
  Etapa 2  Lecturas monótonas: guarda también la posición más nueva que cada sesión ya ha visto,
           para que sus lecturas nunca retrocedan. Deja casi todas las lecturas fuera del primario
           (como mucho un 35%).

Compruébalo:  LABS_LANG=es uv run pytest labs/replication_lag
Mira una solución (¡después de intentarlo!):  labs/replication_lag/es/reference.py
"""

from __future__ import annotations

import random


class Router:
    """Decide adónde va cada lectura. El escenario llama a:

      wrote(session, lsn)               la escritura de una sesión se consolidó en el primario en la
                                        posición `lsn` del log (las posiciones solo crecen)
      pick(session, key, replicas)      una lectura: devuelve "primary" o el nombre de una réplica
      saw(session, key, name, lsn)      tras una lectura: respondió el nodo `name`, y el valor que dio
                                        se escribió en la posición `lsn` (su versión)

    `replicas` es una lista de Replica(name, lsn, up): la posición que cada réplica había aplicado
    en su último informe (cada 100 ms, así que puede estar algo vieja, nunca adelantada), y si
    responde. Las sesiones son ints; las claves, strings. Usa `self.rng` para elegir al azar.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random(0)
        # Etapa 1: un dict sesión -> el LSN de su última escritura.
        # Etapa 2: y, por (sesión, clave), la versión más nueva que ha visto.

    def wrote(self, session: int, lsn: int) -> None:
        pass  # Etapa 1: guárdalo

    def pick(self, session: int, key: str, replicas: list) -> str:
        up = [r.name for r in replicas if r.up]
        # Etapa 1: quédate solo con las réplicas cuyo r.lsn sea al menos la última escritura de la sesión.
        # Etapa 2: ... y al menos la versión de esta clave que la sesión ya vio.
        # Si ninguna réplica sirve, devuelve "primary".
        return self.rng.choice(up) if up else "primary"

    def saw(self, session: int, key: str, name: str, lsn: int) -> None:
        pass  # Etapa 2: guarda la versión más nueva de esta clave que ha visto esta sesión

"""Laboratorio consistent_hashing: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Ocho servidores de caché (c0 ... c7) están delante de una base de datos lenta. Cada lectura va
al servidor que elige `Router.node_for(key)`; un fallo de caché sigue hasta la base de datos.
De vez en cuando el clúster cambia: se cae un nodo, el autoescalado añade uno, un despliegue
reinicia uno. Ahora mismo `Router` usa hash(key) % N, así que cuando N cambia casi todas las
claves pasan a otro servidor, que nunca las ha visto: una tormenta de fallos llega a la base
de datos.

Haz las etapas en orden, en este archivo:

  Etapa 1  Un anillo de hash: pon cada nodo en un círculo, en stable_hash(node); una clave
           es del primer nodo en el sentido de las agujas del reloj desde stable_hash(key).
           Así un cambio solo mueve las claves del nodo que entra o sale (más o menos 1/N).
  Etapa 2  Nodos virtuales: pon cada nodo muchas veces en el anillo (digamos 200 puntos,
           en stable_hash(f"{node}#{i}")), para que cada nodo tenga su parte justa de claves.

Compruébalo:  LABS_LANG=es uv run pytest labs/consistent_hashing
Mira una solución (¡después de intentarlo!):  labs/consistent_hashing/es/reference.py
"""

from __future__ import annotations

import bisect
import hashlib


def stable_hash(text: str) -> int:
    """Un hash de 64 bits que es el mismo en cada proceso y cada ejecución.

    (El hash() de Python para un string cambia de un proceso a otro.)
    """
    return int.from_bytes(hashlib.md5(text.encode()).digest()[:8], "big")


class Router:
    """Elige el servidor de caché de una clave.

    Contrato:
      - `Router(nodes)` empieza con estos nombres de nodo, p. ej. ["c0", ..., "c7"].
      - `node_for(key)` devuelve uno de los nodos que hay ahora en el clúster.
      - `add(node)` y `remove(node)` se llaman cuando cambia el clúster.
      - Mientras el clúster no cambie, la misma clave debe ir siempre al mismo nodo.
    """

    def __init__(self, nodes: list[str]) -> None:
        self.nodes = list(nodes)
        # Etapa 1: construye el anillo en su lugar: una lista ordenada de (stable_hash(node), node).
        # Etapa 2: muchos puntos por nodo: (stable_hash(f"{node}#{i}"), node) para i en range(200).

    def add(self, node: str) -> None:
        self.nodes.append(node)
        # Etapa 1: añade el punto (o los puntos) del nodo al anillo, sin desordenarlo (bisect.insort).

    def remove(self, node: str) -> None:
        self.nodes.remove(node)
        # Etapa 1: quita del anillo el punto (o los puntos) del nodo.

    def node_for(self, key: str) -> str:
        # Etapa 1: busca el primer punto >= stable_hash(key) con bisect.bisect_left sobre los
        # hashes, y vuelve al primer punto si te pasas del final.
        return self.nodes[stable_hash(key) % len(self.nodes)]

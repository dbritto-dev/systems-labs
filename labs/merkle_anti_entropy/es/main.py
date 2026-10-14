"""Laboratorio merkle_anti_entropy: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

4 réplicas (n0 ... n3) de un almacén clave/valor, cada una con una copia completa de las mismas
20.000 claves ("k00000" ... "k19999"), en una red donde cada mensaje tarda ~100 ms. Los clientes
escriben ~100 claves por segundo, cada una en una réplica, que la replica a las demás por lotes; y
leen ~200 claves por segundo de cualquier réplica que esté en pie.

La replicación a veces pierde escrituras, y nadie te avisa: una réplica está caída más tiempo del
que cubren sus pistas, un corte de red pierde un lote, un disco dañado pierde claves, se restaura
una copia vieja sobre un rango de claves. Ahora mismo nada las repara: esas réplicas se quedan
atrás para siempre, y una lectura recibe una versión vieja (o nada) según qué réplica responda.

Haz las etapas en orden, en este archivo:

  Etapa 1  Un barrido completo: cada ROUND segundos, envía al siguiente par la versión de cada
           clave que tienes (`full_scan`, `sync_keys`). Te responde con las entradas que tiene más
           nuevas y las claves que quiere (`on_scan`, con `diff`); guarda las primeras y envíale
           las segundas. Todas las réplicas convergen, pero cada ronda envía 20.000 entradas para
           hallar unos cientos de diferencias.
  Etapa 2  Árboles de Merkle: mantén un árbol de hash sobre el rango de claves (`MerkleTree`),
           actualizado en `changed` en cada cambio. Compara raíces con un par, baja solo por los
           hijos cuyo hash difiere (`merkle_sync`, `on_hashes`), y sincroniza solo las claves de
           las hojas que difieren. Elige DEPTH para que una hoja tenga unas pocas claves.

Lo que tienes (mira labs/merkle_anti_entropy/api.py):
  KEYS, ALL_KEYS, key_of(i), index_of(key)   el rango de claves: key_of(7) == "k00007"
  self.data                     {clave: (versión, valor)}, solo lectura; una versión mayor es más nueva
  self.version(key) -> int      la versión que tiene esta réplica, 0 si no la tiene
  self.store(key, version, value)   la guarda si es más nueva que la nuestra (lo que llama la reparación)
  self.changed(key, old, new)   se llama tras cada cambio de self.data; old/new: (versión, valor) o None
  self.digest(*parts) -> int    un hash de 64 bits; cuesta una unidad de cálculo de hash por parte
  self.peers                    las demás réplicas
  self.rpc(peer, body)          envía una petición y espera la respuesta (TimeoutError si no llega)
  self.send(peer, body), self.reply(msg, body), self.every(seconds, fn)   mira core/net.py
Un mensaje de tipo "x" llama a `async def on_x(self, msg)`. Un mensaje cuesta sus entradas: una por
elemento de cada lista, tupla, conjunto o dict de su cuerpo, más una.

Compruébalo:  LABS_LANG=es uv run pytest labs/merkle_anti_entropy
Mira una solución (¡después de intentarlo!):  labs/merkle_anti_entropy/es/reference.py
"""

from __future__ import annotations

from labs.merkle_anti_entropy.api import ALL_KEYS, KEYS, Message, Replica, index_of, key_of

ROUND = 2.0  # segundos entre dos rondas de reparación, cada una con el siguiente par
FANOUT = 16  # etapa 2: hijos de cada nodo interior del árbol
DEPTH = 3  # etapa 2: niveles bajo la raíz, así que FANOUT ** DEPTH hojas. 1 = 16 hojas de 1.250 claves;
#            3 = 4.096 hojas de ~5 claves; 5 = un millón de hojas, casi todas vacías. Elige bien.


# ---------------------------------------------------------------- etapa 1: barrido completo


def diff(mine: dict, theirs: dict) -> tuple[list, list]:
    """Compara dos mapas {clave: versión} sobre las claves de `theirs` (una clave que falta en
    `mine` es la versión 0). Devuelve (claves donde theirs es más nueva, claves donde mine es más
    nueva).

    diff({"k1": 5, "k2": 3}, {"k1": 4, "k2": 7, "k3": 1}) == (["k2", "k3"], ["k1"])
    """
    # Etapa 1: recorre theirs.items(); compara cada versión con mine.get(key, 0).
    raise NotImplementedError("TODO etapa 1: diff")


# ---------------------------------------------------------------- etapa 2: un árbol de Merkle


class MerkleTree:
    """Etapa 2. Un árbol de hash sobre el rango de claves. El nivel 0 es la raíz (un nodo, índice
    0); el nivel d tiene FANOUT ** d nodos; el nivel `depth` tiene las hojas. La hoja i cubre un
    tramo seguido del rango: la clave número n está en la hoja n * leaves // KEYS.

      leaf_of(key) -> int        la hoja de una clave
      keys_of(leaf) -> list      todas las claves del rango que cubre esa hoja, estén o no
      children(i) -> range       los índices, un nivel más abajo, de los hijos del nodo i
      update(key, old, new)      una clave cambió (old/new: (versión, valor) o None): arregla su hoja
      hash(level, i) -> int      el hash del nodo i en ese nivel, al día

    Que un cambio sea barato: el hash de una hoja es el XOR de digest(key, version, value) de sus
    claves, así que update() saca con XOR el digest viejo y mete el nuevo (dos XOR se anulan). El
    hash de un nodo interior es digest(*los hash de sus hijos). Recalcula solo los ancestros de las
    hojas que cambiaron, y solo cuando te piden hash() (guarda las hojas cambiadas en un conjunto):
    nunca recalcules las 20.000 claves.
    """

    def __init__(self, digest, fanout: int = FANOUT, depth: int = DEPTH) -> None:
        self.digest, self.fanout, self.depth = digest, fanout, depth
        self.leaves = fanout ** depth
        self.levels = [[0] * fanout ** d for d in range(depth + 1)]  # levels[d][i]: hash del nodo i en el nivel d
        self.dirty: set[int] = set()  # hojas que cambiaron desde que se recalcularon sus ancestros

    def leaf_of(self, key: str) -> int:
        raise NotImplementedError("TODO etapa 2: MerkleTree.leaf_of")

    def keys_of(self, leaf: int) -> list[str]:
        # Las claves n con n * leaves // KEYS == leaf: desde ceil(leaf * KEYS / leaves) hasta (sin
        # incluir) ceil((leaf + 1) * KEYS / leaves). Con enteros, ceil(a / b) es -(-a // b).
        raise NotImplementedError("TODO etapa 2: MerkleTree.keys_of")

    def children(self, i: int) -> range:
        raise NotImplementedError("TODO etapa 2: MerkleTree.children")

    def update(self, key: str, old, new) -> None:
        raise NotImplementedError("TODO etapa 2: MerkleTree.update")

    def hash(self, level: int, i: int) -> int:
        # Si cambiaron hojas, recalcula sus padres, luego los de ellos, hasta la raíz (el padre del
        # nodo i es i // fanout); luego responde desde self.levels.
        raise NotImplementedError("TODO etapa 2: MerkleTree.hash")


# ---------------------------------------------------------------- la réplica


class ReplicaNode(Replica):
    """Una réplica. La replicación ya está hecha (api.py); tú escribes la reparación.

    Contrato:
      - cada réplica tiene la última versión de cada clave poco después de un incidente
      - una ronda en calma cuesta poco, y una reparación unas pocas entradas por clave reparada
      - el cálculo de hash sigue siendo poco: actualiza el árbol en cada cambio, nunca lo reconstruyas
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.tree = None  # Etapa 2: MerkleTree(self.digest)
        self.turn = 0
        self.every(ROUND, self.repair)

    def changed(self, key, old, new) -> None:
        pass  # Etapa 2: self.tree.update(key, old, new)

    async def repair(self) -> None:
        """Una ronda de antientropía, cada ROUND segundos, con el siguiente par por turno."""
        peer = self.peers[self.turn % len(self.peers)]
        self.turn += 1
        # Etapa 1: await self.full_scan(peer)
        # Etapa 2: await self.merkle_sync(peer) en su lugar

    # ---- etapa 1: compara cada clave

    async def full_scan(self, peer: str) -> None:
        raise NotImplementedError("TODO etapa 1: full_scan")  # sync_keys con todas las claves: ALL_KEYS

    async def sync_keys(self, peer: str, keys) -> None:
        """Repara `keys` con `peer`, en los dos sentidos."""
        # Etapa 1: reply = await self.rpc(peer, {"type": "scan", "versions": {clave: nuestra versión}})
        #          (cada clave de `keys`, 0 si no la tenemos). Guarda cada una de reply["newer"]
        #          ({clave: (versión, valor)}) con self.store; luego envía al par las entradas que
        #          pidió en reply["want"]: {"type": "entries", "entries": {clave: self.data[clave]}}.
        raise NotImplementedError("TODO etapa 1: sync_keys")

    async def on_scan(self, msg: Message) -> None:
        # Etapa 1: compara con diff nuestras versiones de las claves de msg.body["versions"] con las
        #          suyas; responde {"type": "scan_ok", "newer": {clave: self.data[clave]} de las
        #          claves que tenemos más nuevas, "want": [las claves que ellos tienen más nuevas]}.
        raise NotImplementedError("TODO etapa 1: on_scan")

    async def on_entries(self, msg: Message) -> None:
        for key, (version, value) in msg.body["entries"].items():
            self.store(key, version, value)

    # ---- etapa 2: baja por el árbol donde los hash difieren

    async def merkle_sync(self, peer: str) -> None:
        # Etapa 2: empieza en el nivel 0 con los nodos [0] (la raíz). Pregunta al par cuáles difieren:
        #            reply = await self.rpc(peer, {"type": "hashes", "level": level,
        #                                          "hashes": {i: self.tree.hash(level, i) for i in nodes}})
        #          Si no difiere ninguno: hecho, no hay nada que reparar. En las hojas (level ==
        #          self.tree.depth): sync_keys(peer, todas las claves de las hojas que difieren). Si
        #          no, los hijos de los nodos que difieren son los nodos del siguiente nivel.
        raise NotImplementedError("TODO etapa 2: merkle_sync")

    async def on_hashes(self, msg: Message) -> None:
        # Etapa 2: responde {"type": "hashes_ok", "differ": [i for i, h in msg.body["hashes"].items()
        #          if nuestro hash del nodo i en el nivel msg.body["level"] != h]}.
        raise NotImplementedError("TODO etapa 2: on_hashes")

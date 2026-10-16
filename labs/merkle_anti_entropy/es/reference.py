"""Laboratorio merkle_anti_entropy: una solución que funciona (etapa 2). Léela después de intentar es/main.py.

Antientropía con barrido completo (etapa 1): en cada ronda, envía a un par la versión de cada
clave; responde con lo que tiene más nuevo y pide lo que tenemos más nuevo. Lo repara todo, pero
cada ronda mueve 20,000 entradas para hallar unos cientos de diferencias.

Árboles de Merkle (etapa 2): cada réplica mantiene un árbol de hash sobre su rango de claves,
actualizado en cada cambio (`changed`). Una hoja es el XOR de los digest de sus claves, así que un
cambio son dos digest; un nodo interior es el digest de sus hijos, recalculado solo cuando alguien
lo pide tras un cambio. Dos réplicas comparan raíces, bajan solo por los hijos que difieren, e
intercambian las claves de las hojas que difieren. Una reparación cuesta unas decenas de entradas
por clave, por grande que sea el rango.
"""

from __future__ import annotations

from labs.merkle_anti_entropy.api import ALL_KEYS, KEYS, Message, Replica, index_of, key_of

ROUND = 2.0  # segundos entre dos rondas de reparación, cada una con el siguiente par
FANOUT = 16  # hijos de cada nodo interior del árbol
DEPTH = 3  # niveles bajo la raíz: 16 ** 3 = 4,096 hojas de ~5 claves


# ---------------------------------------------------------------- etapa 1: barrido completo


def diff(mine: dict, theirs: dict) -> tuple[list, list]:
    """(claves donde theirs es más nueva, claves donde mine es más nueva), para las claves de `theirs`."""
    i_need, they_need = [], []
    for key, v in theirs.items():
        m = mine.get(key, 0)
        if v > m:
            i_need.append(key)
        elif m > v:
            they_need.append(key)
    return i_need, they_need


# ---------------------------------------------------------------- etapa 2: un árbol de Merkle


class MerkleTree:
    """Un árbol de hash sobre el rango de claves: el nivel 0 es la raíz, el nivel `depth` las hojas."""

    def __init__(self, digest, fanout: int = FANOUT, depth: int = DEPTH) -> None:
        self.digest, self.fanout, self.depth = digest, fanout, depth
        self.leaves = fanout ** depth
        self.levels = [[0] * fanout ** d for d in range(depth + 1)]
        self.dirty: set[int] = set()  # hojas que cambiaron desde que se recalcularon sus ancestros

    def leaf_of(self, key: str) -> int:
        return index_of(key) * self.leaves // KEYS

    def keys_of(self, leaf: int) -> list[str]:
        lo = -(-leaf * KEYS // self.leaves)
        hi = -(-(leaf + 1) * KEYS // self.leaves)
        return [key_of(i) for i in range(lo, hi)]

    def children(self, i: int) -> range:
        return range(i * self.fanout, (i + 1) * self.fanout)

    def update(self, key: str, old, new) -> None:
        """Una clave cambió: saca con XOR su digest viejo de su hoja y mete el nuevo."""
        leaf = self.leaf_of(key)
        h = self.levels[self.depth][leaf]
        if old is not None:
            h ^= self.digest(key, *old)
        if new is not None:
            h ^= self.digest(key, *new)
        self.levels[self.depth][leaf] = h
        self.dirty.add(leaf)

    def hash(self, level: int, i: int) -> int:
        if self.dirty:
            self.rehash()
        return self.levels[level][i]

    def rehash(self) -> None:
        """Recalcula los ancestros de las hojas cambiadas, de abajo arriba: solo esos."""
        nodes, f = self.dirty, self.fanout
        for d in range(self.depth - 1, -1, -1):
            below, here = self.levels[d + 1], self.levels[d]
            nodes = {i // f for i in nodes}
            for p in nodes:
                here[p] = self.digest(*below[p * f:(p + 1) * f])
        self.dirty = set()


# ---------------------------------------------------------------- la réplica


class ReplicaNode(Replica):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.tree = MerkleTree(self.digest)
        self.turn = 0
        self.every(ROUND, self.repair)

    def changed(self, key, old, new) -> None:
        self.tree.update(key, old, new)

    async def repair(self) -> None:
        """Una ronda de antientropía con el siguiente par."""
        peer = self.peers[self.turn % len(self.peers)]
        self.turn += 1
        await self.merkle_sync(peer)

    # ---- etapa 1: compara cada clave

    async def full_scan(self, peer: str) -> None:
        await self.sync_keys(peer, ALL_KEYS)

    async def sync_keys(self, peer: str, keys) -> None:
        """Envía nuestra versión de cada clave; toma lo que el par tiene más nuevo, envía lo que pide."""
        reply = await self.rpc(peer, {"type": "scan", "versions": {k: self.version(k) for k in keys}})
        for key, (version, value) in reply["newer"].items():
            self.store(key, version, value)
        want = [k for k in reply["want"] if k in self.data]
        if want:
            self.send(peer, {"type": "entries", "entries": {k: self.data[k] for k in want}})

    async def on_scan(self, msg: Message) -> None:
        theirs = msg.body["versions"]
        i_need, they_need = diff({k: self.version(k) for k in theirs}, theirs)
        self.reply(msg, {"type": "scan_ok", "newer": {k: self.data[k] for k in they_need}, "want": i_need})

    async def on_entries(self, msg: Message) -> None:
        for key, (version, value) in msg.body["entries"].items():
            self.store(key, version, value)

    # ---- etapa 2: baja por el árbol donde los hash difieren

    async def merkle_sync(self, peer: str) -> None:
        tree = self.tree
        level, nodes = 0, [0]
        while True:
            reply = await self.rpc(peer, {"type": "hashes", "level": level,
                                          "hashes": {i: tree.hash(level, i) for i in nodes}})
            differ = reply["differ"]
            if not differ:
                return  # iguales: nada que reparar bajo estos nodos
            if level == tree.depth:
                break
            nodes = [c for i in differ for c in tree.children(i)]
            level += 1
        await self.sync_keys(peer, [k for leaf in differ for k in tree.keys_of(leaf)])

    async def on_hashes(self, msg: Message) -> None:
        level = msg.body["level"]
        differ = [i for i, h in msg.body["hashes"].items() if self.tree.hash(level, i) != h]
        self.reply(msg, {"type": "hashes_ok", "differ": differ})

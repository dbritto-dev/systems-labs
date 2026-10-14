"""Laboratorio vector_clocks_crdts: una solución que funciona (etapa 2). Léela después de intentar es/main.py.

Relojes vectoriales (etapa 1): `compare` dice si una versión ocurrió antes que otra o si son
concurrentes, y `keep_newest` guarda cada versión concurrente como hermana. No se pierde nada,
pero una lectura tiene que fusionar las hermanas, y una baja puede volver desde una hermana que
aún tiene el producto.

Un CRDT (etapa 2): cada carrito es un conjunto de bajas observadas (OR-set). Cada alta lleva una
etiqueta única; una baja pone lápida a las etiquetas que esta réplica ha visto; fusionar es unir
las dos cosas. Las fusiones pueden llegar en cualquier orden, cualquier número de veces, y todas
las réplicas acaban con el mismo carrito: ningún alta perdida, y nada quitado vuelve (un alta que
quien quitó no había visto sobrevive, como debe ser).
"""

from __future__ import annotations

from core.net import Message, Node

GOSSIP = 1.0  # segundos entre dos rondas de anti-entropía (cada carrito, a cada par)


# ---------------------------------------------------------------- etapa 1: relojes vectoriales


def compare(a: dict, b: dict) -> str:
    """Cómo se relaciona el reloj de versión `a` con `b`: "equal", "before", "after" o "concurrent"."""
    a_le = all(n <= b.get(node, 0) for node, n in a.items())
    b_le = all(n <= a.get(node, 0) for node, n in b.items())
    if a_le and b_le:
        return "equal"
    if a_le:
        return "before"
    if b_le:
        return "after"
    return "concurrent"


def keep_newest(versions: list) -> list:
    """Las hermanas: cada versión (clock, items) de la que no desciende ninguna otra, una vez cada una."""
    out: list = []
    for clock, items in versions:
        if any(compare(clock, other) in ("before", "equal") for other, _ in out):
            continue  # ya guardamos esta, o una más nueva
        out = [(c, i) for c, i in out if compare(c, clock) != "before"]
        out.append((clock, items))
    return out


# ---------------------------------------------------------------- etapa 2: un CRDT


class ORSet:
    """Un conjunto de bajas observadas: etiquetas vivas por producto, más las lápidas de las quitadas."""

    def __init__(self) -> None:
        self.tags: dict[str, set] = {}  # producto -> sus etiquetas vivas (altas que nadie quitó aún)
        self.removed: set = set()  # lápidas: cada etiqueta quitada alguna vez

    def add(self, item: str, tag: str) -> None:
        self.tags.setdefault(item, set()).add(tag)

    def remove(self, item: str) -> None:
        """Quita lo que hemos visto: pon lápida a las etiquetas del producto que conocemos."""
        self.removed |= self.tags.pop(item, set())

    def items(self) -> set[str]:
        return {item for item, tags in self.tags.items() if tags}

    def merge(self, other: "ORSet") -> None:
        new = other.removed - self.removed
        if new:
            self.removed |= new
            for item, tags in self.tags.items():
                tags -= new
        for item, tags in other.tags.items():
            mine = self.tags.setdefault(item, set())
            if not tags <= mine:
                mine |= tags - self.removed

    def copy(self) -> "ORSet":
        out = ORSet()
        out.tags = {item: set(tags) for item, tags in self.tags.items() if tags}
        out.removed = set(self.removed)
        return out


class CartNode(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.skew = 0.0  # lo pone el escenario
        self.peers = [n for n in node_ids if n != node_id]
        self.carts: dict[str, ORSet] = {}
        self.added = 0  # altas hechas aquí: con nuestro id, una etiqueta que nadie más crea
        self.every(GOSSIP, self.gossip)

    def clock(self) -> float:
        """El reloj de pared de esta máquina, como time.time(). (Dado: un ajuste de NTP lo hace mentir.)"""
        return self.now() + self.skew

    # ---- el carrito, como CRDT

    def cart(self, cart: str) -> ORSet:
        return self.carts.setdefault(cart, ORSet())

    def items(self, cart: str) -> set[str]:
        entry = self.carts.get(cart)
        return entry.items() if entry else set()

    def add(self, cart: str, item: str) -> None:
        self.added += 1
        self.cart(cart).add(item, f"{self.node_id}:{self.added}")

    def remove(self, cart: str, item: str) -> None:
        self.cart(cart).remove(item)

    def state(self, cart: str) -> ORSet:
        return self.carts[cart].copy()  # una copia: el mensaje no debe cambiar después de enviarlo

    def merge(self, cart: str, theirs: ORSet) -> None:
        self.cart(cart).merge(theirs)

    # ---- clientes y difusión (igual en todas las etapas)

    async def on_add(self, msg: Message) -> None:
        self.add(msg.body["cart"], msg.body["item"])
        self.push(msg.body["cart"])
        self.reply(msg, {"type": "add_ok"})

    async def on_remove(self, msg: Message) -> None:
        self.remove(msg.body["cart"], msg.body["item"])
        self.push(msg.body["cart"])
        self.reply(msg, {"type": "remove_ok"})

    async def on_read(self, msg: Message) -> None:
        self.reply(msg, {"type": "read_ok", "items": sorted(self.items(msg.body["cart"]))})

    def push(self, cart: str) -> None:
        """Cuéntale un cambio a cada par al momento (se pierde si la red está partida)."""
        body = {"type": "sync", "carts": {cart: self.state(cart)}}
        for peer in self.peers:
            self.send(peer, body)

    async def gossip(self) -> None:
        """Anti-entropía: cada carrito a cada par, para que una réplica que se perdió envíos se ponga al día."""
        if not self.carts:
            return
        body = {"type": "sync", "carts": {cart: self.state(cart) for cart in self.carts}}
        for peer in self.peers:
            self.send(peer, body)

    async def on_sync(self, msg: Message) -> None:
        for cart, theirs in msg.body["carts"].items():
            self.merge(cart, theirs)

"""Lab vector_clocks_crdts: a working solution (stage 2). Read it after you have tried main.py.

Vector clocks (stage 1): `compare` tells whether one version happened before another or whether
they are concurrent, and `keep_newest` keeps every concurrent version as a sibling. Nothing is
lost, but a read must merge the siblings, and a remove can come back from a sibling that still
holds the item.

A CRDT (stage 2): each cart is an observed-remove set (OR-set). Every add gets a unique tag; a
remove tombstones the tags this replica has seen; merging is a union of both. Merges can come in
any order, any number of times, and every replica ends up with the same cart: no lost adds, and a
removed item never comes back (an add the remover had not seen survives, as it should).
"""

from __future__ import annotations

from core.net import Message, Node

GOSSIP = 1.0  # seconds between two rounds of anti-entropy (every cart, to every peer)


# ---------------------------------------------------------------- stage 1: vector clocks


def compare(a: dict, b: dict) -> str:
    """How version clock `a` relates to `b`: "equal", "before", "after" or "concurrent"."""
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
    """The siblings: every (clock, items) version that no other version descends from, once each."""
    out: list = []
    for clock, items in versions:
        if any(compare(clock, other) in ("before", "equal") for other, _ in out):
            continue  # we already keep this one, or a newer one
        out = [(c, i) for c, i in out if compare(c, clock) != "before"]
        out.append((clock, items))
    return out


# ---------------------------------------------------------------- stage 2: a CRDT


class ORSet:
    """An observed-remove set: live tags per item, plus the tombstones of removed tags."""

    def __init__(self) -> None:
        self.tags: dict[str, set] = {}  # item -> its live tags (adds nobody has removed yet)
        self.removed: set = set()  # tombstones: every tag ever removed

    def add(self, item: str, tag: str) -> None:
        self.tags.setdefault(item, set()).add(tag)

    def remove(self, item: str) -> None:
        """Remove what we have seen: tombstone the item's tags we know."""
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
        self.skew = 0.0  # set by the scenario
        self.peers = [n for n in node_ids if n != node_id]
        self.carts: dict[str, ORSet] = {}
        self.added = 0  # adds made here: with our id, a tag nobody else makes
        self.every(GOSSIP, self.gossip)

    def clock(self) -> float:
        """This machine's wall clock, like time.time(). (Given: an NTP step makes it lie.)"""
        return self.now() + self.skew

    # ---- the cart, as a CRDT

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
        return self.carts[cart].copy()  # a copy: the message must not change after we send it

    def merge(self, cart: str, theirs: ORSet) -> None:
        self.cart(cart).merge(theirs)

    # ---- clients and gossip (the same at every stage)

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
        """Tell every peer about a change right away (lost if the network is split)."""
        body = {"type": "sync", "carts": {cart: self.state(cart)}}
        for peer in self.peers:
            self.send(peer, body)

    async def gossip(self) -> None:
        """Anti-entropy: every cart to every peer, so a replica that missed pushes catches up."""
        if not self.carts:
            return
        body = {"type": "sync", "carts": {cart: self.state(cart) for cart in self.carts}}
        for peer in self.peers:
            self.send(peer, body)

    async def on_sync(self, msg: Message) -> None:
        for cart, theirs in msg.body["carts"].items():
            self.merge(cart, theirs)

"""Lab vector_clocks_crdts: YOUR FILE. Edit it and save; the live window reruns it.

Shared shopping carts, multi-leader. 5 replicas, one per site, on a network where every message
takes ~100 ms. Every replica takes adds and removes right away from the devices near it (no
leader, works offline) and gossips its carts to the others. A cart is shared by two devices
that talk to two different replicas, so the same cart is edited in two places at once.

Right now each cart is one value stamped with the replica's wall clock, and the newest stamp
wins (last write wins, like Cassandra's cells). Two edits of a cart made at the same time on two
replicas cannot both win: one of them is silently dropped. And when a clock jumps (NTP), an old
write with a wrong stamp beats every newer one.

Do the stages in order, in this file:

  Stage 1  Vector clocks: stamp every version with a vector clock ({replica: count}) instead of
           the time. `compare` tells you whether one version happened before another or whether
           they are concurrent; keep every concurrent version as a sibling (`keep_newest`), and
           merge the siblings when you read. No add is lost any more, but a remove can come back.
  Stage 2  A CRDT: make each cart an observed-remove set (`ORSet`). Every add gets a unique tag,
           a remove tombstones the tags this replica has seen, and merging two sets is a union.
           Every replica ends with the same cart: nothing lost, nothing back from the dead.

How your node talks (see core/net.py):
  self.node_id, self.node_ids      who you are, and every replica ("n0" ... "n4")
  self.reply(msg, {...})           answer a request
  self.send(dest, {...})           fire and forget (dropped while the network is split)
  self.every(seconds, coroutine_function)    run something periodically
  self.now()                       the true time (only the checker may use it: real machines
                                   only have self.clock(), which can be wrong)

The network hands the receiver the very objects you put in a message: never change something
after you sent it (send copies, or values you never change: tuples, frozensets).

The checker calls `items(cart)` on every replica (keep it fast, and keep it the cart a read
returns). Each device only removes its own products, and only after it added them.

Check yourself:  uv run pytest labs/vector_clocks_crdts
Peek at a solution (after trying!):  labs/vector_clocks_crdts/reference.py
"""

from __future__ import annotations

from core.net import Message, Node

GOSSIP = 1.0  # seconds between two rounds of anti-entropy (every cart, to every peer)


# ---------------------------------------------------------------- stage 1: vector clocks


def compare(a: dict, b: dict) -> str:
    """How version clock `a` relates to clock `b`. A clock is {replica id: count}; a missing
    replica counts 0.

      "equal"       the same counts
      "before"      a happened before b: every count of a <= b's, and they differ
      "after"       b happened before a
      "concurrent"  neither: each has seen something the other has not (a conflict)

    compare({"n0": 1}, {"n0": 1, "n1": 2}) == "before"
    compare({"n0": 2}, {"n1": 1}) == "concurrent"
    """
    # Stage 1: a_le = every count in a is <= the same count in b (b.get(node, 0)); b_le the same
    #          the other way round. Both: equal; only a_le: before; only b_le: after; neither:
    #          concurrent.
    raise NotImplementedError("TODO stage 1: compare")


def keep_newest(versions: list) -> list:
    """The siblings: from (clock, items) versions, drop each one that another version descends
    from (it is "before" another, or "equal" to one already kept). What is left are the versions
    nobody has seen past: one when there was no conflict, several when there was.

    keep_newest([({"n0": 1}, A), ({"n0": 2}, B)]) == [({"n0": 2}, B)]
    keep_newest([({"n0": 1}, A), ({"n1": 1}, B)]) == both, as siblings
    """
    # Stage 1: build a list `out`; for each version, skip it if some kept clock is "after" or
    #          "equal" to it (compare(clock, kept) in ("before", "equal")), else remove the kept
    #          ones that are "before" it and keep it.
    raise NotImplementedError("TODO stage 1: keep_newest")


# ---------------------------------------------------------------- stage 2: a CRDT


class ORSet:
    """Stage 2. An observed-remove set: the cart as a CRDT.

      add(item, tag)    tag: unique in the whole system, e.g. f"{node_id}:{n}" with n counting up
      remove(item)      tombstone every tag of `item` this replica has seen (an add it has not
                        seen yet is not removed: it wins)
      items() -> set    the items with at least one tag that is not a tombstone
      merge(other)      union of the tags and union of the tombstones: order and repeats do not
                        matter (commutative, associative, idempotent)
      copy() -> ORSet   a copy to put in a message

    Hint: keep `self.tags = {item: set of live tags}` and `self.removed = set of tombstones`;
    items() is then quick: the items whose set of tags is not empty.
    """

    def __init__(self) -> None:
        self.tags: dict[str, set] = {}
        self.removed: set = set()

    def add(self, item: str, tag: str) -> None:
        raise NotImplementedError("TODO stage 2: ORSet.add")

    def remove(self, item: str) -> None:
        raise NotImplementedError("TODO stage 2: ORSet.remove")

    def items(self) -> set[str]:
        raise NotImplementedError("TODO stage 2: ORSet.items")

    def merge(self, other: "ORSet") -> None:
        # Take the new tombstones first and drop them from your live tags; then add their live
        # tags, minus your tombstones.
        raise NotImplementedError("TODO stage 2: ORSet.merge")

    def copy(self) -> "ORSet":
        raise NotImplementedError("TODO stage 2: ORSet.copy")


class CartNode(Node):
    """One replica: it takes the writes of the devices near it and gossips with the others.

    Contract:
      - `add` {cart, item}     -> reply {"type": "add_ok"} (right away: no waiting for peers)
      - `remove` {cart, item}  -> reply {"type": "remove_ok"}
      - `read` {cart}          -> reply {"type": "read_ok", "items": [...]}
      - `items(cart)` -> set   what a read would return (the checker calls it)
    Every replica ends with the same carts, with every acknowledged add and no removed item.
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.skew = 0.0  # set by the scenario
        self.peers = [n for n in node_ids if n != node_id]
        # Stage 0: cart -> ((wall clock, node id), frozenset of items): one value, newest stamp wins.
        # Stage 1: cart -> [(vector clock, frozenset of items), ...]: the siblings.
        # Stage 2: cart -> ORSet.
        self.carts: dict = {}
        self.every(GOSSIP, self.gossip)

    def clock(self) -> float:
        """This machine's wall clock, like time.time(). (Given: an NTP step makes it lie.)"""
        return self.now() + self.skew

    # ---- the cart: change these at each stage

    def items(self, cart: str) -> set[str]:
        # Stage 1: the union of the siblings' items (merging on read).
        # Stage 2: self.carts[cart].items().
        entry = self.carts.get(cart)
        return set(entry[1]) if entry else set()

    def add(self, cart: str, item: str) -> None:
        # Stage 2: an ORSet add with a new tag (count your adds: f"{self.node_id}:{n}").
        self.put(cart, self.items(cart) | {item})

    def remove(self, cart: str, item: str) -> None:
        # Stage 2: ORSet remove.
        self.put(cart, self.items(cart) - {item})

    def put(self, cart: str, items: set[str]) -> None:
        """A local write of the whole cart."""
        # Stage 1: the new clock is the max of every sibling's clock, per replica, plus 1 for
        #          self.node_id; the write replaces all the siblings it read:
        #          self.carts[cart] = [(clock, frozenset(items))]. Make a new dict for the clock:
        #          never change one you may have sent.
        self.carts[cart] = ((self.clock(), self.node_id), frozenset(items))

    def state(self, cart: str):
        """What to send a peer about one cart."""
        # Stage 1: list(self.carts[cart]).  Stage 2: a copy of the ORSet.
        return self.carts[cart]

    def merge(self, cart: str, theirs) -> None:
        """Fold a peer's version of a cart into ours."""
        # Stage 1: self.carts[cart] = keep_newest(our siblings + theirs).
        # Stage 2: merge their ORSet into ours (make an empty one if we have none).
        mine = self.carts.get(cart)
        if mine is None or tuple(theirs[0]) > tuple(mine[0]):
            self.carts[cart] = theirs  # last write wins: the other version is gone

    # ---- clients and gossip (given: the same at every stage)

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

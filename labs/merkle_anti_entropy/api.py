"""What your ReplicaNode gets: one replica of a key/value store, on a simulated network.

Think of Cassandra, Riak or Dynamo's storage nodes: 4 replicas (n0 ... n3) each hold a copy of the
same 20,000 keys, "k00000" ... "k19999", in key order (a key range). Every value carries a version:
a higher version is a newer write, and wins.

    KEYS, key_of(i), index_of(key)      the key range: key_of(7) == "k00007", index_of("k00007") == 7
    ALL_KEYS                            every key, in order

    Replica (your ReplicaNode subclasses it; it is a core.net.Node):
      self.data                         {key: (version, value)}, read-only: change it with store()
      self.version(key) -> int          the version this replica holds, 0 if it has none
      self.store(key, version, value)   keep it if it is newer than what we hold; True if it changed
      self.changed(key, old, new)       YOUR hook, called after every change of self.data, whatever
                                        made it (a client write, replication, your repair, a restored
                                        backup, a bad disk). old and new are (version, value) or None.
      self.digest(*parts) -> int        a 64-bit hash of the parts. Hashing costs CPU: one unit of
                                        "hash work" per part
      self.peers                        the other replicas: ["n0", "n1", ...] without this one
      and what every core.net.Node has  self.rpc, self.send, self.reply, self.every, self.now()

Replication is given. A client writes to one replica (the coordinator), which sends the write to
every peer in a batch every 0.1 s ("replicate" messages). While the coordinator knows a peer is
down it keeps hints instead, at most HINTS per peer, and replays them when the peer is back
(hinted handoff); writes past that are never sent. A message lost on the network is lost.

What a message costs: its entries. Every item of a list, tuple, set or dict in its body is one
entry (a key with its version, a hash, a node index), plus one for the message itself.
"""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType

from core.net import Message, Node

KEYS = 20_000
HINTS = 50  # writes a coordinator keeps for a peer it knows is down (Cassandra: the hint window)
BATCH = 0.1  # seconds between two replication batches to each peer
MASK = (1 << 64) - 1

__all__ = ["ALL_KEYS", "HINTS", "KEYS", "Message", "Replica", "entries", "index_of", "key_of"]


def key_of(i: int) -> str:
    """The i-th key of the range: key_of(7) == "k00007"."""
    return f"k{i:05d}"


def index_of(key: str) -> int:
    """Where a key sits in the range: index_of("k00007") == 7."""
    return int(key[1:])


ALL_KEYS = tuple(key_of(i) for i in range(KEYS))


def entries(body: dict) -> int:
    """What a message costs: one per item of every list, tuple, set or dict in it, plus one."""
    n = 1
    for v in body.values():
        if isinstance(v, (list, tuple, dict, set, frozenset)):
            n += len(v)
    return n


type Entry = tuple[int, int]  # (version, value)


class Replica(Node):
    """One replica: its data, the given replication, and the hooks your ReplicaNode fills in."""

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.peers = [n for n in node_ids if n != node_id]
        self._data: dict[str, Entry] = {}
        self.data = MappingProxyType(self._data)  # read-only: change it with store()
        self.hashed = 0  # hash work so far (the scenario reads it)
        self.fixed = 0  # keys changed by repair so far (the scenario reads it)
        self.overflow = 0  # writes never sent to a down peer: its hints were full
        self.down_peers: set[str] = set()  # what the failure detector says (set by the scenario)
        self.watch: Callable[[Replica, str, int], None] | None = None  # the checker (set by the scenario)
        self._outbox: dict[str, dict[str, Entry]] = {p: {} for p in self.peers}
        self._hints: dict[str, dict[str, Entry]] = {p: {} for p in self.peers}
        self.every(BATCH, self._flush)

    # ---- the data

    def version(self, key: str) -> int:
        e = self._data.get(key)
        return e[0] if e is not None else 0

    def store(self, key: str, version: int, value: int) -> bool:
        """Keep (version, value) for key if it is newer than ours. What repair calls."""
        return self._apply(key, version, value, repair=True)

    def changed(self, key: str, old: Entry | None, new: Entry | None) -> None:
        """Called after every change of self.data. Your ReplicaNode overrides it."""

    def digest(self, *parts) -> int:
        """A 64-bit hash of the parts; costs one unit of hash work per part."""
        self.hashed += len(parts)
        return hash(parts) & MASK

    def _apply(self, key: str, version: int, value: int, repair: bool = False) -> bool:
        old = self._data.get(key)
        if old is not None and old[0] >= version:
            return False
        if repair:
            self.fixed += 1
        self._set(key, (version, value), old)
        return True

    def _set(self, key: str, new: Entry | None, old: Entry | None) -> None:
        if new is None:
            self._data.pop(key, None)
        else:
            self._data[key] = new
        self.changed(key, old, new)
        if self.watch is not None:
            self.watch(self, key, new[0] if new else 0)

    # ---- for the scenario: client writes, bulk loads, and what incidents do to the disk

    def load(self, rows: dict[str, Entry]) -> None:
        """The data this replica starts with (each row goes through changed(); not counted as work)."""
        for key, e in rows.items():
            self._set(key, e, self._data.get(key))
        self.hashed = 0

    def write(self, key: str, version: int, value: int) -> None:
        """A client write with this replica as the coordinator: keep it, and replicate it."""
        self._apply(key, version, value)
        for p in self.peers:
            if p in self.down_peers:
                hints = self._hints[p]
                if len(hints) < HINTS or key in hints:
                    hints[key] = (version, value)
                else:
                    self.overflow += 1  # the hint window is full: this write never reaches p
            else:
                self._outbox[p][key] = (version, value)

    def force(self, key: str, entry: Entry | None) -> None:
        """The disk changed under us: a lost key (None) or an old version from a backup."""
        old = self._data.get(key)
        if old != entry:
            self._set(key, entry, old)

    def peer_up(self, peer: str) -> None:
        """The failure detector says `peer` is back: replay its hints."""
        self.down_peers.discard(peer)
        hints, self._hints[peer] = self._hints[peer], {}
        if hints:
            self.send(peer, {"type": "replicate", "entries": hints})

    async def _flush(self) -> None:
        for p in self.peers:
            batch = self._outbox[p]
            if batch:
                self._outbox[p] = {}
                self.send(p, {"type": "replicate", "entries": batch})

    async def on_replicate(self, msg: Message) -> None:
        for key, (version, value) in msg.body["entries"].items():
            self._apply(key, version, value)

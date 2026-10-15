"""The pictures for lab chain_replication: pipeline (the chain as a row of boxes, head first, the
nodes out of it after a gap), cluster (the chain left to right, head first: writes flow down it,
acknowledgements climb back) and lanes (the clients' view: their reads and writes, the
chain as the server)."""

from __future__ import annotations

from labs.chain_replication import lab
from labs.chain_replication.scenario import M_ACK, M_GET, M_PUT, M_REPLICATE, M_SNAPSHOT, M_WRITE
from live.adapters.common import FLY, client_lanes, every
from live.canvas import BG, BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, MUTED, ORANGE, RED, WHITE, mix
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_pipeline import Leaf, PipelineAdapter, PipelineFrame

MAX_FLIGHTS = 60  # messages drawn at once
DROP_FADE = 0.6  # seconds a lost message stays on screen
COLOURS = {M_PUT: WHITE, M_GET: MUTED, M_WRITE: BLUE, M_REPLICATE: BLUE, M_ACK: GREEN, M_SNAPSHOT: EXTRA1}
SHOWN = set(COLOURS)  # answers to the clients and the master's messages are not drawn
INFLIGHT_MAX = 40  # writes waiting in the chain that fill the server's gauge
SENT_MAX = 10  # writes a node has passed down and not seen acknowledged that fill its box's gauge
RECONFIGURE = 0.5  # seconds after the chain changes that the door stays shut (the clients learn the new one)


def _behind(keys: int) -> tuple[int, int, int]:
    if keys == 0:
        return BLUE
    return EXTRA1 if keys <= 3 else EXTRA2 if keys <= 10 else EXTRA3


def order(st: tuple | None) -> list[int]:
    """The nodes left to right: the chain, head first, then the ones out of it."""
    from live.worlds.chain_replication import ST_CHAIN

    chain = list(st[ST_CHAIN]) if st is not None else list(range(lab.NODES))
    return chain + [i for i in range(lab.NODES) if i not in chain]


@adapts("chain_replication", "cluster")
class ChainCluster(ClusterAdapter):
    """The chain, head on the left and tail on the right, a word under each node (head, tail, down,
    copying). Writes come in from the clients (white) to the head and flow right (blue); the tail's
    acknowledgements climb back left (green); reads (grey) go to the node `read_from` picks. A node
    copying the tail's state is light orange, and so is the copy on its way (it takes ~1 s). A node
    is red while it is down or out of the chain, orange while slow, and light to deep orange when it
    misses acknowledged writes. A lost message stops half way and fades in red."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.chain_replication import (
            MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC, ST_BEHIND, ST_CHAIN, ST_DOWN, ST_JOINING, ST_SLOW,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        st = w.state_at(variant, t)
        slots = order(st)
        where = {node: k for k, node in enumerate(slots)}
        nodes, labels = [], []
        for i in slots:
            name = f"n{i}"
            if st is None:
                nodes.append(BLUE)
                labels.append((name, MUTED))
                continue
            chain = st[ST_CHAIN]
            if st[ST_DOWN] >> i & 1:
                nodes.append(RED)
                labels.append((w.s("role", node=name, role=w.s("role_down")), RED))
            elif st[ST_JOINING] >> i & 1:
                nodes.append(EXTRA1)
                labels.append((w.s("role", node=name, role=w.s("role_copying")), EXTRA1))
            elif i not in chain:
                nodes.append(MUTED)
                labels.append((w.s("role", node=name, role=w.s("role_out")), MUTED))
            else:
                nodes.append(ORANGE if st[ST_SLOW] == i else _behind(st[ST_BEHIND][i]))
                role = "role_head" if i == chain[0] else "role_tail" if i == chain[-1] else ""
                labels.append((w.s("role", node=name, role=w.s(role)) if role else name,
                               WHITE if role else MUTED))
        flights, drops = [], []
        recent = [m for m in run.rows("msgs", t - lab.COPY * 1.5, t + 1e-9) if m[MSG_KIND] in SHOWN]
        for m in every(recent, MAX_FLIGHTS * 3):
            src, dest = where.get(m[MSG_SRC], -1), where.get(m[MSG_DEST], -1)
            if src == dest:
                continue
            arrived = m[MSG_ARRIVED]
            if arrived is None:
                if t - m[MSG_SENT] < DROP_FADE:
                    drops.append((src, dest, (t - m[MSG_SENT]) / DROP_FADE))
                continue
            span = max(FLY, arrived - m[MSG_SENT])  # slowed down to be seen; a slow node's take longer
            p = (t - m[MSG_SENT]) / span
            if p < 1.0:
                flights.append((src, dest, p, COLOURS[m[MSG_KIND]]))
        text, colour = w.situation(variant, t)
        return ClusterFrame(nodes=nodes, flights=every(flights, MAX_FLIGHTS), drops=every(drops, 20),
                            state=(text, colour), columns=len(nodes), labels=labels)


# ---------------------------------------------------------------- the lanes picture: the clients' view


@adapts("chain_replication", "lanes")
class ChainLanes(LaneAdapter):
    """The clients' view: reads and writes fly to the door (the head for writes, red while the chain
    is down, orange while a node is slow) and the chain is the server, its gauge the writes waiting
    in it. An answer is green, red when a read missed an acknowledged write or an acknowledged write
    was lost, orange when nobody answered in time."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.chain_replication import OP_END, OP_LOST, OP_OK, OP_STALE, OP_START, ST_INFLIGHT

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def colour(o):
            return RED if o[OP_STALE] or o[OP_LOST] else GREEN if o[OP_OK] else EXTRA2

        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, colour=colour,
                                                   rare_first=True)
        st = w.state_at(variant, t)
        inflight = st[ST_INFLIGHT] if st else 0
        text, state_colour = w.situation(variant, t, short=True)
        door = None if state_colour in (GREEN, EXTRA1, EXTRA2) else state_colour
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, door_color=door,
                         fill=inflight / INFLIGHT_MAX, gauge=EXTRA2 if inflight > INFLIGHT_MAX / 2 else BLUE,
                         outline=RED if state_colour == RED else OUTLINE, state=(text, state_colour))


# ---------------------------------------------------------------- the pipeline picture: the chain as a row


@adapts("chain_replication", "pipeline")
class ChainPipeline(PipelineAdapter):
    """The clients are the users and the door; the chain is a row of boxes, head on the left, tail on
    the right, and the nodes out of it come after a gap, dimmed ("n1 down"). The door shuts while the
    chain reconfigures (a node in it is down, or it has just changed). Writes come in from the clients
    (white) to the head and hop right along the chain (blue); the tail's acknowledgements hop back left
    (green); reads (grey) fly on an arc from the door to the node `read_from` picks; anything else
    that skips a node (a primary writing to every backup, a resend round a dead node, the tail's copy
    to a joining node, light orange) flies on an arc too. A lost message fades red where it was.
    Each box's gauge: the writes it has passed down and not seen acknowledged. Outlines: red down,
    orange slow, light orange while copying."""

    def frame(self, variant: str, t: float, users: int) -> PipelineFrame:
        from live.worlds.chain_replication import (
            MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC, OP_END, OP_LOST, OP_OK, OP_STALE, OP_START,
            ST_CHAIN, ST_DOWN, ST_JOINING, ST_SENT, ST_SLOW,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return PipelineFrame()

        def colour(o):
            return RED if o[OP_STALE] or o[OP_LOST] else GREEN if o[OP_OK] else EXTRA2

        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, colour=colour,
                                                   rare_first=True)
        st = w.state_at(variant, t)
        slots = order(st)
        where = {node: k for k, node in enumerate(slots)}
        chain = list(st[ST_CHAIN]) if st is not None else slots
        boxes = []
        for i in slots:
            name = f"n{i}"
            sent = st[ST_SENT][i] if st is not None and len(st) > ST_SENT else 0
            line, role, col = OUTLINE, "", MUTED
            if st is not None and st[ST_DOWN] >> i & 1:
                line, role, col = RED, "role_down", RED
            elif st is not None and st[ST_JOINING] >> i & 1:
                line, role, col = EXTRA1, "role_copying", EXTRA1
            elif i not in chain:
                role = "role_out"
            elif st is not None and st[ST_SLOW] == i:
                line, col = ORANGE, ORANGE
            if not role and i in chain:
                role = "role_head" if i == chain[0] else "role_tail" if i == chain[-1] else ""
                col = col if col != MUTED else WHITE if role else MUTED
            label = w.s("role", node=name, role=w.s(role)) if role else name
            boxes.append(Leaf((label, col), sent / SENT_MAX, EXTRA2 if sent > SENT_MAX / 2 else BLUE, line,
                              short=name))
        hops, skips, drops = [], [], []
        recent = [m for m in run.rows("msgs", t - lab.COPY * 1.5 - FLY, t + 1e-9) if m[MSG_KIND] in SHOWN]
        for m in every(recent, MAX_FLIGHTS * 3):
            src, dest = where.get(m[MSG_SRC], -1), where.get(m[MSG_DEST], -1)
            if src == dest or dest < 0:
                continue
            sent, arrived = m[MSG_SENT], m[MSG_ARRIVED]
            if src < 0:
                sent += FLY  # from the door: after the client's flight there
            kind = m[MSG_KIND]
            if arrived is None:
                if 0 <= t - sent < DROP_FADE:
                    fade = (t - sent) / DROP_FADE
                    if dest == src + 1 or src == dest + 1:
                        drops.append((max(src, dest), fade))
                    else:
                        skips.append((src, dest, 0.5, mix(RED, BG, fade)))
                continue
            p = (t - sent) / max(FLY, arrived - m[MSG_SENT])  # slowed down to be seen; a slow node's take longer
            if not 0.0 <= p < 1.0:
                continue
            tint = MUTED if kind == M_GET else COLOURS[kind]
            if dest == src + 1:
                hops.append((dest, p, tint, False))  # down the chain (or a client's call to the head)
            elif src == dest + 1 and src >= 0:
                hops.append((src, p, tint, True))  # back up the chain
            else:
                skips.append((src, dest, p, tint))  # over the nodes in between
        out = [i for i in slots if i not in chain]
        changed = any(r[ST_CHAIN] != (st[ST_CHAIN] if st else ()) for r in run.rows("state", t - RECONFIGURE, t + 1e-9))
        down = st is not None and any(st[ST_DOWN] >> i & 1 for i in chain)
        text, state_colour = w.situation(variant, t, short=True)
        return PipelineFrame(users=waiting, flights=flights, outcomes=outcomes, closed=down or changed,
                             door_color=RED if down else EXTRA2 if changed else None,
                             boxes=boxes, hops=every(hops, MAX_FLIGHTS), skips=every(skips, MAX_FLIGHTS),
                             drops=every(drops, 20), gap_after=len(chain) - 1 if out else None,
                             state=(text, state_colour))

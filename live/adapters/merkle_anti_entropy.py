"""The pictures for lab merkle_anti_entropy: the replicas drifting apart and repairing, and the clients' reads."""

from __future__ import annotations

from live.adapters.common import client_lanes, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, ORANGE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame

DROP_FADE = 0.6  # seconds a dropped message stays on screen
MAX_FLIGHTS = 80
MAX_CLIENTS = 8  # client requests shown at once (a sample: there are ~300 a second)
CLIENT_FLY = 0.1  # seconds a client request takes to reach its replica (cosmetic)


def _repair_colour(entries: int):
    """A repair message, by what it carries: a few hashes, a leaf's keys, or a whole key range."""
    return EXTRA1 if entries <= 50 else EXTRA2 if entries <= 2_000 else EXTRA3


@adapts("merkle_anti_entropy", "cluster")
class MerkleCluster(ClusterAdapter):
    """The replicas: blue when they hold the latest version of every key, deeper orange the more keys
    they miss, red while down. Replication batches fly between them in blue, repair messages in orange
    (deeper the more entries they carry: a full scan is a deep orange stream); while a replica is cut
    off, messages to and from it are dropped half way, in red. Client reads and writes come in white."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.merkle_anti_entropy import (MSG_ARRIVED, MSG_DEST, MSG_ENTRIES, MSG_REPAIR, MSG_SENT,
                                                    MSG_SRC, OP_NODE, OP_START, diverged_at, shade)

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        diverged = diverged_at(run, t)
        nodes = [shade(k) for k in diverged]
        cut = w.cut_at(variant, t)
        if cut is not None and cut[0] == "down":
            nodes[cut[1]] = RED
        repair, replication, drops = [], [], []
        for m in run.rows("msgs", t - DROP_FADE, t + 1e-9):
            arrived = m[MSG_ARRIVED]
            if arrived is None:
                drops.append((m[MSG_SRC], m[MSG_DEST], (t - m[MSG_SENT]) / DROP_FADE))
            elif t < arrived:
                p = (t - m[MSG_SENT]) / max(1e-6, arrived - m[MSG_SENT])
                if m[MSG_REPAIR]:
                    repair.append((m[MSG_SRC], m[MSG_DEST], p, _repair_colour(m[MSG_ENTRIES])))
                else:
                    replication.append((m[MSG_SRC], m[MSG_DEST], p, BLUE))
        clients = [(-1, o[OP_NODE], (t - o[OP_START]) / CLIENT_FLY, WHITE)
                   for o in run.rows("ops", t - CLIENT_FLY, t + 1e-9)]
        flights = repair[:MAX_FLIGHTS // 2]  # repair first: it is the lesson
        flights += every(replication, (MAX_FLIGHTS - len(flights)) // 2)
        flights += every(clients, min(MAX_CLIENTS, MAX_FLIGHTS - len(flights)))
        groups = None
        total = sum(diverged)
        if cut is not None:
            groups = [0 if i == cut[1] else 1 for i in range(len(nodes))]
            word = w.s("state_down", node=f"n{cut[1]}") if cut[0] == "down" else w.screen.STATES["partitioned"]
            state = (word, RED)
        elif total:
            state = (w.s("state_diverged", n=total), ORANGE)
        else:
            state = (w.s("state_sync"), GREEN)
        return ClusterFrame(nodes=nodes, groups=groups, flights=flights, drops=every(drops, 30), state=state)


# ---------------------------------------------------------------- the lanes picture: the clients' view

GAUGE_MAX = 20_000  # repair entries per second that fill the gauge
RECENT = 2.0  # seconds a stale read keeps the state on it


@adapts("merkle_anti_entropy", "lanes")
class MerkleLanes(LaneAdapter):
    """The clients' view: reads and writes, each answered by one replica (the door, orange while some
    replica holds older versions). A read is green when it got the latest version, red when it got an
    older one (a stale read). The server's gauge is the repair traffic: full in a full scan."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.merkle_anti_entropy import OP_END, OP_STALE, OP_START, diverged_at

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def colour(o):
            return RED if o[OP_STALE] else GREEN

        waiting, flights, outcomes = client_lanes(run, t, users, "ops", OP_START, OP_END, colour=colour,
                                                   rare_first=True)
        s = int(t)
        sent = sum(run.series("repair", s - 1, s))
        fill = min(1.0, sent / GAUGE_MAX)
        stale = any(o[OP_STALE] for o in run.rows("ops", t - RECENT, t + 1e-9) if o[OP_END] <= t)
        total = sum(diverged_at(run, t))
        cut = w.cut_at(variant, t)
        if stale:
            state = (w.s("lanes_stale"), RED)
        elif cut is not None and cut[0] == "down":
            state = (w.screen.STATES["degraded"], ORANGE)
        elif total:
            state = (w.s("lanes_diverged"), ORANGE)
        else:
            state = (w.s("lanes_sync"), GREEN)
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes,
                         door_color=ORANGE if total else None, fill=fill,
                         gauge=EXTRA2 if fill > 0.5 else BLUE, outline=RED if stale else OUTLINE, state=state)

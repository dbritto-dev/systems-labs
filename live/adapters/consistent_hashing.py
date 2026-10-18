"""The pictures for lab consistent_hashing: the cache servers, coloured by their share of keys, and
reads flying to the server that owns each key (red when it misses); and the clients' view."""

from __future__ import annotations

from live.adapters.common import client_lanes, every
from live.canvas import BLUE, DIM, EXTRA1, EXTRA2, GREEN, ORANGE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_fanin import FaninAdapter, FaninFrame, Leaf

FLY = 0.3  # seconds a read takes to reach its server (cosmetic: a hit takes ~1 ms)
DROP_FADE = 0.6  # seconds a read the database refused stays on screen
MAX_FLIGHTS = 60


@adapts("consistent_hashing", "cluster")
class ConsistentHashingCluster(ClusterAdapter):
    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.consistent_hashing import lab
        from live.worlds.consistent_hashing import R_HIT, R_OK, R_SLOT, R_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights, drops = [], []
        for r in run.rows("reads", t - DROP_FADE, t + 1e-9):
            age = t - r[R_START]
            if not r[R_OK]:
                drops.append((-1, r[R_SLOT], age / DROP_FADE))
            elif age <= FLY:
                flights.append((-1, r[R_SLOT], age / FLY, WHITE if r[R_HIT] else RED))
        db = run.count("reads", t - 1, t) - sum(1 for r in run.rows("reads", t - 1, t) if r[R_HIT])
        words, per_s = w.screen.STATES, w.s("tile_db")
        if db >= lab.DB_CAPACITY * 0.75:
            state = (f"{words['overloaded']}  {per_s} {db}", RED)
        elif db >= lab.DB_CAPACITY * 0.4:
            state = (f"{words['busy']}  {per_s} {db}", ORANGE)
        else:
            state = (f"{words['healthy']}  {per_s} {db}", GREEN)
        return ClusterFrame(nodes=w.node_colours(variant, t), flights=every(flights, MAX_FLIGHTS),
                            drops=every(drops, 30), state=state)


# ---------------------------------------------------------------- the lanes picture: the clients' view


@adapts("consistent_hashing", "lanes")
class ConsistentHashingLanes(LaneAdapter):
    """The clients' view: reads through the cache servers (the door) to the database (the server, its
    gauge the database's reads/s against its capacity). An answer is green from the cache, orange when
    it missed and went to the database, red when the database refused it."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from labs.consistent_hashing import lab
        from live.worlds.consistent_hashing import R_END, R_HIT, R_OK, R_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def colour(r):
            return GREEN if r[R_HIT] else EXTRA2 if r[R_OK] else RED

        waiting, flights, outcomes = client_lanes(run, t, users, "reads", R_START, R_END, colour=colour)
        last = run.rows("reads", t - 1, t)
        db = sum(1 for r in last if not r[R_HIT])
        hits = 1 - db / len(last) if last else 1.0
        if db >= lab.DB_CAPACITY * 0.75:
            state, gauge = (w.s("lanes_misses", share=1 - hits), RED), RED
        elif db >= lab.DB_CAPACITY * 0.4:
            state, gauge = (w.s("lanes_misses", share=1 - hits), ORANGE), ORANGE
        else:
            state, gauge = (w.s("lanes_hits", share=hits), GREEN), BLUE
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes, fill=db / lab.DB_CAPACITY,
                         gauge=gauge, outline=RED if db >= lab.DB_CAPACITY * 0.75 else OUTLINE, state=state)


# ---------------------------------------------------------------- the fan-in picture: router, caches, database

HOP = 0.2  # seconds a read takes from the router to its cache server, and a miss on to the database (cosmetic)
MAX_HOPS, MAX_JOINS = 36, 80
DIED = 3.0  # seconds a node that just went down stays red
CALM = 15.0  # seconds before a change that give each server its usual misses/s


def _flooded(run, t: float, layout) -> set[int]:
    """The cache servers missing far more than usual right now (their keys just moved to them): misses in
    the last second over twice that server's calm rate, the calm being the 15 s before the last change."""
    from live.worlds.consistent_hashing import C_LIVE, C_T, R_HIT, R_SLOT

    if layout is None:
        return set()
    since = layout[C_T] if layout[C_T] > 0 else t
    calm: dict[int, int] = {}
    for r in run.rows("reads", since - CALM, since):
        if not r[R_HIT]:
            calm[r[R_SLOT]] = calm.get(r[R_SLOT], 0) + 1
    usual = sum(calm.values()) / CALM / max(1, sum(layout[C_LIVE]))  # for a server new to the cluster
    now: dict[int, int] = {}
    for r in run.rows("reads", t - 1, t + 1e-9):
        if not r[R_HIT]:
            now[r[R_SLOT]] = now.get(r[R_SLOT], 0) + 1
    return {j for j, n in now.items() if n > 2 * (calm[j] / CALM if j in calm else usual) + 3}


@adapts("consistent_hashing", "fanin")
class ConsistentHashingFanin(FaninAdapter):
    """Reads come through the router (the door) to the cache server that owns the key (c0..c8, each
    gauge its share of keys against the average, full at 2x); a miss goes on to the one database (the
    store, its gauge the database's reads/s against its capacity): orange as usual, red from a server
    missing far more than usual (its keys just moved to it) or when the database refused it. With hash % N, after a node dies every server misses at once; with a ring,
    only the one that took its keys."""

    def frame(self, variant: str, t: float, users: int) -> FaninFrame:
        from labs.consistent_hashing import lab
        from labs.consistent_hashing.scenario import SLOTS
        from live.adapters.common import FLY
        from live.worlds.consistent_hashing import C_COUNTS, C_LIVE, C_OP, C_SLOT, C_T, R_HIT, R_OK, R_SLOT, R_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return FaninFrame()
        lane = ConsistentHashingLanes(w).frame(variant, t, users)  # users, flights and outcomes as in lanes
        layout = w.layout(variant, t)
        flooded = _flooded(run, t, layout)
        hops, joins = [], []
        rows = run.rows("reads", t - FLY - 2 * HOP, t + 1e-9)
        for r in every([r for r in rows if FLY <= t - r[R_START] < FLY + HOP], MAX_HOPS):
            hops.append((r[R_SLOT], (t - r[R_START] - FLY) / HOP, WHITE, False))
        for r in every([r for r in rows if not r[R_HIT] and FLY + HOP <= t - r[R_START]], MAX_JOINS):
            red = r[R_SLOT] in flooded or not r[R_OK]
            joins.append((r[R_SLOT], (t - r[R_START] - FLY - HOP) / HOP, RED if red else EXTRA2, False))

        died = {c[C_SLOT] for c in run.data.get("changes", []) if c[C_OP] == "remove" and t - DIED <= c[C_T] <= t}
        leaves = []
        for j, node in enumerate(SLOTS):
            on = layout is not None and layout[C_LIVE][j]
            if not on:
                red = j in died
                leaves.append(Leaf((node, RED if red else DIM),  # just removed: red (the legend)
                                   short=node, outline=RED if red else DIM))
                continue
            live = [n for n, alive in zip(layout[C_COUNTS], layout[C_LIVE]) if alive]
            share = layout[C_COUNTS][j] / (sum(live) / len(live))
            colour = BLUE if share <= 1.2 else EXTRA1 if share <= lab.BALANCE_MAX else EXTRA2
            leaves.append(Leaf((node, WHITE), fill=share / 2, gauge=colour, outline=OUTLINE))

        db = sum(1 for r in run.rows("reads", t - 1, t) if not r[R_HIT])
        words = w.screen.STATES
        if db >= lab.DB_CAPACITY * 0.75:
            word, colour = words["overloaded"], RED
        elif db >= lab.DB_CAPACITY * 0.4:
            word, colour = words["busy"], ORANGE
        else:
            word, colour = words["healthy"], GREEN
        return FaninFrame(users=lane.users, flights=lane.flights, outcomes=lane.outcomes,
                          fill=db / lab.DB_CAPACITY, gauge=BLUE if colour == GREEN else colour,
                          outline=RED if colour == RED else OUTLINE, state=(w.s("fan_db", state=word, db=db), colour),
                          leaves=leaves, hops=hops, joins=joins, door_label=(w.s("fan_router"), DIM))

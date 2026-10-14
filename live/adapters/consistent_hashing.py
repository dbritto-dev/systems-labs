"""The cluster picture for lab consistent_hashing: the cache servers, coloured by their share of
keys, and reads flying to the server that owns each key (red when it misses)."""

from __future__ import annotations

from live.adapters.common import every
from live.canvas import GREEN, ORANGE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame

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

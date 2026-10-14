"""The pictures for lab transactional_outbox: cluster (the order service, its database, the relay, the
broker and shipping, with the messages between them) and lanes (orders through the order service, the
door, to its database, the server, whose gauge is the outbox backlog)."""

from __future__ import annotations

from labs.transactional_outbox.scenario import (
    AGAIN, DROPPED, FAILED, GHOST, PHANTOM, POD, RELAY, RELAY_ONLY, SHIPPED, SKIPPED,
)
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, MUTED, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

OUTBOX_MAX = 500.0  # unsent outbox rows that fill the gauge
HOP = 0.25  # seconds a message dot takes from one node to the next (cosmetic: real hops take ~1 ms)
FADE = 0.6  # seconds a lost or phantom event stays on screen


def _rare_first(rows: list, bad, most: int) -> list:
    """At most `most` rows, the bad ones first, so a few among hundreds still show."""
    red = every([r for r in rows if bad(r)], most)
    room = most - len(red)
    return red + (every([r for r in rows if not bad(r)], room) if room > 0 else [])


@adapts("transactional_outbox", "cluster")
class OutboxCluster(ClusterAdapter):
    """The topology, on a 3 x 2 grid:

        service (0)   database (1)   relay (2)
        shipping (3)  broker (4)

    Orders fly in from the clients to the service, and on to the database when they commit (white).
    The dual write publishes from the service straight to the broker (white); with an outbox, the
    relay takes rows from the database (blue) and publishes them (white, light orange when it is a
    second time). The broker delivers to shipping: green when it ships, deep orange when it ships an
    order a second time, red for an order that was never saved, grey when shipping skips a repeat.
    A lost event (saved, never announced) and a phantom (announced, then rolled back) fade in red
    half way. A killed process turns red; the broker turns red while it is down.
    """

    SERVICE, DB, RELAY, SHIPPING, BROKER = 0, 1, 2, 3, 4

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.transactional_outbox import (
            D_KIND, D_T, O_COMMIT, O_END, O_OUTCOME, O_START, P_OK, P_REPEAT, P_T, P_WHO, POLL_N, POLL_T,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights, drops = [], []
        for o in every(run.rows("orders", t - FLY, t + 1e-9), FLIGHTS):  # orders arrive
            flights.append((-1, self.SERVICE, (t - o[O_START]) / FLY, WHITE))
        span = run.max_dur.get("orders", 0.0)
        commits = [o for o in run.rows("orders", t - HOP - span, t + 1e-9)
                   if o[O_COMMIT] is not None and t - HOP <= o[O_COMMIT] <= t]
        flights += [(self.SERVICE, self.DB, (t - o[O_COMMIT]) / HOP, WHITE) for o in every(commits, FLIGHTS)]
        for p in run.rows("polls", t - HOP, t + 1e-9):  # the relay takes rows from the outbox
            if p[POLL_N]:
                flights.append((self.DB, self.RELAY, (t - p[POLL_T]) / HOP, BLUE))
        pubs = run.rows("publishes", t - HOP, t + 1e-9)
        for p in _rare_first(pubs, lambda p: not p[P_OK] or p[P_REPEAT], FLIGHTS):
            src = self.RELAY if p[P_WHO] == RELAY else self.SERVICE
            if p[P_OK]:
                flights.append((src, self.BROKER, (t - p[P_T]) / HOP, EXTRA1 if p[P_REPEAT] else WHITE))
            else:
                drops.append((src, self.BROKER, (t - p[P_T]) / HOP))
        colours = {SHIPPED: GREEN, AGAIN: EXTRA3, GHOST: RED, SKIPPED: MUTED}
        deliveries = run.rows("deliveries", t - HOP, t + 1e-9)
        for d in _rare_first(deliveries, lambda d: d[D_KIND] in (AGAIN, GHOST), FLIGHTS):
            flights.append((self.BROKER, self.SHIPPING, (t - d[D_T]) / HOP, colours[d[D_KIND]]))
        # Lost events (saved, nothing announced) and phantoms (announced, then rolled back) fade half way.
        bad = [o for o in run.rows("orders", t - FADE - span, t + 1e-9)
               if t - FADE <= o[O_END] <= t and o[O_OUTCOME] in (DROPPED, PHANTOM)]
        for o in every(bad, OUTCOMES):
            drops.append((self.SERVICE, self.BROKER if o[O_OUTCOME] == DROPPED else self.DB,
                          (t - o[O_END]) / FADE))

        down = w.down_at(run, t)
        inc = w.incident_at(variant, t)
        kind = inc.kind if inc is not None else ""
        twice = any(d[D_KIND] in (AGAIN, GHOST) for d in run.rows("deliveries", t - 1, t + 1e-9))
        outbox = w.outbox_at(run, t)
        nodes = [
            RED if POD in down else BLUE,
            EXTRA2 if kind == "locks" or outbox >= 50 else BLUE,
            RED if POD in down or RELAY_ONLY in down else BLUE,
            RED if twice else EXTRA2 if kind == "rebalance" else BLUE,
            RED if kind == "broker" else BLUE,
        ]
        text, colour = w.state_at(variant, t)
        return ClusterFrame(nodes=nodes, flights=flights, drops=drops,
                            state=(w.s("pic_state", state=text), colour))


@adapts("transactional_outbox", "lanes")
class OutboxLanes(LaneAdapter):
    """Each order is a user; it flies to the order service (the door); its database is the server, and
    the gauge is the outbox backlog. Outcomes at the door: green saved and announced (or queued in the
    outbox), red lost (saved, its event gone) or phantom (its event out, the order rolled back), grey
    failed cleanly (nothing saved, nothing announced). The door is shut while the pod restarts."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.transactional_outbox import O_END, O_ID, O_OUTCOME, O_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        found = {slot(o[O_ID], users): (WHITE, True) for o in run.active("orders", t, O_END)}
        flying = run.rows("orders", t - FLY, t + 1e-9)
        flights = [(slot(o[O_ID], users), (t - o[O_START]) / FLY, WHITE, False) for o in every(flying, FLIGHTS)]
        span = run.max_dur.get("orders", 0.0)
        ended = [o for o in run.rows("orders", t - BACK - span, t + 1e-9) if t - BACK <= o[O_END] <= t]

        def colour(o: tuple):
            return RED if o[O_OUTCOME] in (DROPPED, PHANTOM) else MUTED if o[O_OUTCOME] == FAILED else GREEN

        shown = _rare_first(ended, lambda o: colour(o) == RED, OUTCOMES)
        outcomes = [(colour(o), (t - o[O_END]) / BACK) for o in shown]
        down = w.down_at(run, t)
        inc = w.incident_at(variant, t)
        outbox = w.outbox_at(run, t)
        text, state_colour = w.state_at(variant, t)
        if outbox:
            text = w.s("lane_state", state=text, n=outbox)
        busy = outbox >= 50
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes,
            closed=POD in down,  # the pod is restarting: connection refused
            door_color=EXTRA2 if inc is not None and inc.kind == "broker" else None,
            fill=min(1.0, outbox / OUTBOX_MAX), gauge=EXTRA2 if busy else BLUE,
            outline=EXTRA2 if inc is not None and inc.kind == "locks" else OUTLINE,
            state=(text, state_colour),
        )


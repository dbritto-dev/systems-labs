"""The pictures for lab transactional_outbox: pipeline (the order service, its database, the relay, the
broker and shipping in a row, the dual write over them), cluster (the same five, with the
messages between them) and lanes (orders through the order service, the
door, to its database, the server, whose gauge is the outbox backlog)."""

from __future__ import annotations

from labs.transactional_outbox.scenario import (
    AGAIN, DROPPED, FAILED, GHOST, PHANTOM, POD, REBALANCED, RELAY, RELAY_ONLY, SHIPPED, SKIPPED,
)
from live.adapters.common import (
    FLIGHTS, FLY, OUTCOMES, every, just_ended, just_sent, rare_rows_first, user_flights, user_outcomes,
)
from live.canvas import BG, BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, MUTED, RED, WHITE, mix
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_pipeline import Leaf, PipelineAdapter, PipelineFrame

OUTBOX_MAX = 500.0  # unsent outbox rows that fill the gauge
HOP = 0.25  # seconds a message dot takes from one node to the next (cosmetic: real hops take ~1 ms)
FADE = 0.6  # seconds a lost or phantom event stays on screen
OPEN_MAX = 10.0  # open transactions that fill the order service's gauge (the pipeline picture)
RELAY_MAX = 20.0  # rows the relay has fetched and not published yet that fill its gauge
BROKER_MAX = 50.0  # events published and not consumed yet that fill the broker's gauge


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
        for o in every(just_sent(run, "orders", t), FLIGHTS):  # orders arrive
            flights.append((-1, self.SERVICE, (t - o[O_START]) / FLY, WHITE))
        span = run.max_dur.get("orders", 0.0)
        commits = [o for o in run.rows("orders", t - HOP - span, t + 1e-9)
                   if o[O_COMMIT] is not None and t - HOP <= o[O_COMMIT] <= t]
        flights += [(self.SERVICE, self.DB, (t - o[O_COMMIT]) / HOP, WHITE) for o in every(commits, FLIGHTS)]
        for p in run.rows("polls", t - HOP, t + 1e-9):  # the relay takes rows from the outbox
            if p[POLL_N]:
                flights.append((self.DB, self.RELAY, (t - p[POLL_T]) / HOP, BLUE))
        pubs = run.rows("publishes", t - HOP, t + 1e-9)
        for p in rare_rows_first(pubs, lambda p: not p[P_OK] or p[P_REPEAT], FLIGHTS):
            src = self.RELAY if p[P_WHO] == RELAY else self.SERVICE
            if p[P_OK]:
                flights.append((src, self.BROKER, (t - p[P_T]) / HOP, EXTRA1 if p[P_REPEAT] else WHITE))
            else:
                drops.append((src, self.BROKER, (t - p[P_T]) / HOP))
        colours = {SHIPPED: GREEN, AGAIN: EXTRA3, GHOST: RED, SKIPPED: MUTED}
        deliveries = run.rows("deliveries", t - HOP, t + 1e-9)
        for d in rare_rows_first(deliveries, lambda d: d[D_KIND] in (AGAIN, GHOST), FLIGHTS):
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
        flying = just_sent(run, "orders", t)
        flights = user_flights(every(flying, FLIGHTS), t, O_START, lambda o: (slot(o[O_ID], users), WHITE, False))
        ended = just_ended(run, "orders", O_END, t)

        def colour(o: tuple):
            return RED if o[O_OUTCOME] in (DROPPED, PHANTOM) else MUTED if o[O_OUTCOME] == FAILED else GREEN

        outcomes = user_outcomes(ended, t, O_END, colour, rare=lambda o: colour(o) == RED)
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



@adapts("transactional_outbox", "pipeline")
class OutboxPipeline(PipelineAdapter):
    """The five in a row: the order service, its database, the relay, the broker and shipping. Each
    order is a user; it flies to the door (shut while the pod restarts) and hops on to the service;
    a commit hops to the database (white), the relay's polls take rows from it (blue), its publishes go
    to the broker (white, light orange when it is a second time; grey back when the broker refuses),
    and the broker delivers to shipping: green when it ships, deep orange when it ships an order a
    second time, red for an order that was never saved, grey when it skips a repeat.

    The dual write (stage 0) publishes from the service straight to the broker: a line over the
    database and the relay. A lost event (saved, never announced) or a phantom (announced, then
    rolled back) dies half way along it in red. With an outbox that line is gone: every event goes
    through the database. Gauges: the service's open transactions, the outbox rows not sent yet,
    the rows the relay has in hand, the events the broker holds that shipping has not read. Outlines:
    red when killed or down; the database orange from 50 unsent rows or during a locks incident;
    shipping red when it ships twice or ships a phantom, orange while it rebalances."""

    def frame(self, variant: str, t: float, users: int) -> PipelineFrame:
        from live.worlds.transactional_outbox import (
            D_KIND, D_ORDER, D_T, O_COMMIT, O_END, O_ID, O_OUTCOME, O_START, P_OK, P_ORDER, P_REPEAT, P_T,
            P_WHO, POLL_N, POLL_T,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return PipelineFrame()
        active = run.active("orders", t, O_END)
        found = {slot(o[O_ID], users): (WHITE, True) for o in active}
        flying = run.rows("orders", t - FLY - HOP, t + 1e-9)
        flights = user_flights(every([o for o in flying if o[O_START] >= t - FLY], FLIGHTS), t, O_START,
                               lambda o: (slot(o[O_ID], users), WHITE, False))
        hops = [(0, (t - o[O_START] - FLY) / HOP, WHITE, False)  # on from the door when the flight gets there
                for o in every([o for o in flying if o[O_START] < t - FLY], FLIGHTS)]
        span = run.max_dur.get("orders", 0.0)
        commits = [o for o in run.rows("orders", t - HOP - span, t + 1e-9)
                   if o[O_COMMIT] is not None and t - HOP <= o[O_COMMIT] <= t]
        hops += [(1, (t - o[O_COMMIT]) / HOP, WHITE, False) for o in every(commits, FLIGHTS)]
        hops += [(2, (t - p[POLL_T]) / HOP, BLUE, False) for p in run.rows("polls", t - HOP, t + 1e-9) if p[POLL_N]]
        skips = []
        pubs = run.rows("publishes", t - HOP, t + 1e-9)
        for p in rare_rows_first(pubs, lambda p: not p[P_OK] or p[P_REPEAT], FLIGHTS):
            colour = EXTRA1 if p[P_REPEAT] else WHITE
            if p[P_WHO] == RELAY:
                hops.append((3, (t - p[P_T]) / HOP, colour, False) if p[P_OK] else
                            (3, (t - p[P_T]) / HOP, MUTED, True))  # the broker refused: back, to retry
            elif p[P_OK]:
                skips.append((0, 3, (t - p[P_T]) / HOP, colour))  # the dual write: over the database
        colours = {SHIPPED: GREEN, AGAIN: EXTRA3, GHOST: RED, SKIPPED: MUTED}
        deliveries = run.rows("deliveries", t - HOP, t + 1e-9)
        for d in rare_rows_first(deliveries, lambda d: d[D_KIND] in (AGAIN, GHOST), FLIGHTS):
            hops.append((4, (t - d[D_T]) / HOP, colours[d[D_KIND]], False))
        bad = [o for o in run.rows("orders", t - FADE - span, t + 1e-9)
               if t - FADE <= o[O_END] <= t and o[O_OUTCOME] in (DROPPED, PHANTOM)]
        skips += [(0, 3, 0.5, mix(RED, BG, (t - o[O_END]) / FADE)) for o in every(bad, OUTCOMES)]

        ended = just_ended(run, "orders", O_END, t)

        def colour(o: tuple):
            return RED if o[O_OUTCOME] in (DROPPED, PHANTOM) else MUTED if o[O_OUTCOME] == FAILED else GREEN

        outcomes = user_outcomes(ended, t, O_END, colour, rare=lambda o: colour(o) == RED)

        # What each one holds.
        opened = sum(1 for o in active if o[O_COMMIT] is None or o[O_COMMIT] > t)
        outbox = w.outbox_at(run, t)
        polls = [p for p in run.rows("polls", t - 2.0, t + 1e-9) if p[POLL_N]]
        recent = run.rows("publishes", t - 2.0, t + 1e-9)
        in_hand = 0
        if polls:
            last = polls[-1]
            in_hand = max(0, last[POLL_N] - sum(1 for p in recent if p[P_WHO] == RELAY and p[P_T] >= last[POLL_T]))
        read = {}
        for d in run.rows("deliveries", t - 2.0, t + 1e-9):
            read[d[D_ORDER]] = max(read.get(d[D_ORDER], 0.0), d[D_T])
        unread = sum(1 for p in recent if p[P_OK] and read.get(p[P_ORDER], -1.0) < p[P_T])

        down = w.down_at(run, t)
        inc = w.incident_at(variant, t)
        kind = inc.kind if inc is not None else ""
        twice = any(d[D_KIND] in (AGAIN, GHOST) for d in run.rows("deliveries", t - 1, t + 1e-9))
        busy = outbox >= 50
        db = w.s("box_db_n", n=outbox) if outbox else w.s("box_db")
        outlines = [
            RED if POD in down else OUTLINE,
            EXTRA2 if kind == "locks" or busy else OUTLINE,
            RED if POD in down or RELAY_ONLY in down else OUTLINE,
            RED if kind == "broker" else OUTLINE,
            RED if twice else EXTRA2 if kind == "rebalance" or REBALANCED in down else OUTLINE,
        ]
        names = [(w.s("box_service"), w.s("box_service_short"), w.s("box_service_tiny")),
                 (db, w.s("box_db"), w.s("box_db")),
                 (w.s("box_relay"), w.s("box_relay_short"), w.s("box_relay_tiny")),
                 (w.s("box_broker"), w.s("box_broker_short"), w.s("box_broker_tiny")),
                 (w.s("box_shipping"), w.s("box_shipping_short"), w.s("box_shipping_tiny"))]
        fills = [(opened / OPEN_MAX, BLUE), (outbox / OUTBOX_MAX, EXTRA2 if busy else BLUE),
                 (in_hand / RELAY_MAX, BLUE), (unread / BROKER_MAX, BLUE), (0.0, BLUE)]
        boxes = [Leaf((name, WHITE if line == OUTLINE else line), fill, gauge, line, short=short, tiny=tiny)
                 for (name, short, tiny), (fill, gauge), line in zip(names, fills, outlines)]
        text, state_colour = w.state_at(variant, t)
        return PipelineFrame(users=found, flights=flights, outcomes=outcomes, closed=POD in down,
                             boxes=boxes, hops=hops, skips=skips, state=(text, state_colour))

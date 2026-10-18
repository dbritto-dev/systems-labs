"""The pictures for lab webhook_delivery: cluster (the dispatcher, four worker nodes of six workers each and
the 20 customer endpoints as nodes), lanes (the events waiting on the left, the dispatcher as the door,
the worker pool as the server) and fanout (the dispatcher in the middle, five endpoints on the right)."""

from __future__ import annotations

from labs.webhook_delivery.api import ENDPOINTS, WORKERS
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, SLOW, every, just_sent, rare_rows_first, user_flights
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, PINK, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import GRID_COLS, OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_fanout import FanoutAdapter, FanoutFrame, Leaf
from live.views.lanes_relay import Relay

SIDE = 5  # the grid is 5 x 5: column 0 the dispatcher and the workers, columns 1-4 the endpoints
DISPATCHER = 2 * SIDE  # row 2, column 0
WORKER_NODES = (0, SIDE, 3 * SIDE, 4 * SIDE)  # rows 0, 1, 3, 4 of column 0
PER_NODE = WORKERS // len(WORKER_NODES)  # workers drawn as one node


def endpoint_node(e: int) -> int:
    """Endpoint e (0-based) in columns 1-4, top to bottom then left to right: #1-#5 in column 1."""
    return (e % SIDE) * SIDE + 1 + e // SIDE


def worker_node(worker: int) -> int:
    return WORKER_NODES[min(len(WORKER_NODES) - 1, worker // PER_NODE)]


def _endpoint_colours(w, run, t: float) -> list:
    """Each endpoint by its health right now: red down, pink hanging, orange slow, purple while it gets
    malformed events, blue healthy."""
    from live.worlds.webhook_delivery import sick

    colours = [BLUE] * ENDPOINTS
    inc = w.incident_at(run, t)
    bad = sick(inc)
    if bad >= 0:
        colours[bad] = {"down": RED, "hang": PINK, "slow": EXTRA2}.get(inc.kind, PURPLE)
    return colours


def _ooo_ids(run, rows: list[tuple]) -> set[int]:
    """The ids among these attempts whose delivery came out of order."""
    from live.worlds.webhook_delivery import AT_END, AT_OK, DL_ID, DL_OOO

    ok = [r for r in rows if r[AT_OK]]
    if not ok:
        return set()
    a, b = min(r[AT_END] for r in ok), max(r[AT_END] for r in ok)
    return {d[DL_ID] for d in run.rows("delivered", a - 1e-6, b + 1e-6) if d[DL_OOO]}


def _picture_state(w, run, variant: str, t: float):
    from live.worlds.webhook_delivery import SM_BUSY

    word, colour = w.state(run, variant, t)
    sample = w.sample_at(run, t)
    return w.s("pic_state", state=word, busy=sample[SM_BUSY] if sample else 0, of=WORKERS), colour


@adapts("webhook_delivery", "cluster")
class WebhookCluster(ClusterAdapter):
    """The dispatcher (left, middle) between four worker nodes (six workers each), and the 20 customer
    endpoints in four columns (#1-#5 first; #1 is the biggest customer).

    New events fly from the shop (left) to the dispatcher (white). Each attempt flies to a worker node and
    on to its endpoint (white the first, oranges for retries); an attempt still waiting for an answer sits
    by its endpoint, orange, so workers stuck on a dead endpoint pile up next to it. An answer flies back
    green (deep orange when it came out of order); a failure dies red on the way; an event given up flies
    back to the shop in purple. An endpoint is red while it is dead (down or hanging), orange while slow,
    purple while it gets malformed events; a worker node turns orange as its six workers fill up; the
    dispatcher turns orange, then red, as its backlog grows.
    """

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.webhook_delivery import (
            AT_END, AT_ENDPOINT, AT_ID, AT_N, AT_OK, AT_START, AT_WORKER, EV_CREATED, GU_T, SM_PENDING,
            attempt_colour,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights: list[tuple] = []
        drops: list[tuple] = []
        flights += [(-1, DISPATCHER, (t - e[EV_CREATED]) / FLY, WHITE)
                    for e in every(just_sent(run, "events", t), FLIGHTS)]
        for r in every(just_sent(run, "attempts", t), FLIGHTS):
            p = (t - r[AT_START]) / FLY
            node = worker_node(r[AT_WORKER])
            if p < 0.4:
                flights.append((DISPATCHER, node, p / 0.4, attempt_colour(r[AT_N])))
            else:
                flights.append((node, endpoint_node(r[AT_ENDPOINT]), (p - 0.4) / 0.6, attempt_colour(r[AT_N])))
        waiting = [r for r in w.in_flight(run, t) if r[AT_START] < t - FLY]
        for r in every(waiting, FLIGHTS):  # still waiting for an answer: it sits by its endpoint
            waited = t - r[AT_START]
            colour = EXTRA1 if waited < 1.0 else EXTRA2 if waited < 2.0 else EXTRA3
            flights.append((worker_node(r[AT_WORKER]), endpoint_node(r[AT_ENDPOINT]), 0.85, colour))
        ended = w.ended(run, t, BACK)
        late = _ooo_ids(run, ended)
        failed = [r for r in ended if not r[AT_OK]]
        shown = every(failed, OUTCOMES) + every([r for r in ended if r[AT_OK]], OUTCOMES)
        for r in shown:
            p = (t - r[AT_END]) / BACK
            node, ep = worker_node(r[AT_WORKER]), endpoint_node(r[AT_ENDPOINT])
            if r[AT_OK]:
                flights.append((ep, node, p, EXTRA3 if r[AT_ID] in late else GREEN))
            else:
                drops.append((node, ep, p))
        for g in every(run.rows("gaveup", t - BACK, t + 1e-9), OUTCOMES):
            flights.append((DISPATCHER, -1, (t - g[GU_T]) / BACK, PURPLE))

        nodes = [BLUE] * (SIDE * SIDE)
        busy = [0] * len(WORKER_NODES)
        for r in w.in_flight(run, t):
            busy[WORKER_NODES.index(worker_node(r[AT_WORKER]))] += 1
        for k, n in enumerate(WORKER_NODES):
            share = busy[k] / PER_NODE
            nodes[n] = BLUE if share < 0.5 else EXTRA1 if share < 0.8 else EXTRA2 if share < 1 else EXTRA3
        sample = w.sample_at(run, t)
        pending = sample[SM_PENDING] if sample else 0
        nodes[DISPATCHER] = RED if pending > w.rate * 10 else EXTRA2 if pending > w.rate * 2 else BLUE
        for e, colour in enumerate(_endpoint_colours(w, run, t)):
            nodes[endpoint_node(e)] = colour
        return ClusterFrame(nodes=nodes, flights=flights, drops=drops, state=_picture_state(w, run, variant, t))


@adapts("webhook_delivery", "lanes")
class WebhookLanes(LaneAdapter):
    """Each event waiting for delivery is a circle on the left, orange the longer it waits. Attempts fly to
    the door (the dispatcher): white the first, oranges for retries. What happened fades at the door: green
    delivered, deep orange delivered out of order, red failed, purple given up. The server is the pool of
    24 workers: its gauge is the share busy, its outline red while half of them are stuck on one endpoint."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.webhook_delivery import (
            AT_END, AT_ID, AT_N, AT_OK, AT_START, EV_CREATED, EV_ID, GU_T, SM_BUSY, attempt_colour, sick,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        found = {}
        for e in w.pending_events(run, t):
            waited = t - e[EV_CREATED]
            shade = WHITE if waited < SLOW[0] else EXTRA1 if waited < SLOW[1] else EXTRA2 if waited < SLOW[2] \
                else EXTRA3
            found[slot(e[EV_ID], users)] = (shade, True)
        flying = just_sent(run, "attempts", t)
        shown = rare_rows_first(flying, lambda r: r[AT_N] > 1, FLIGHTS, FLIGHTS // 2)
        flights = user_flights(shown, t, AT_START,
                               lambda r: (slot(r[AT_ID], users), attempt_colour(r[AT_N]), r[AT_N] > 1))
        ended = w.ended(run, t, BACK)
        late = _ooo_ids(run, ended)
        coloured = [(GREEN if r[AT_OK] and r[AT_ID] not in late else EXTRA3 if r[AT_OK] else RED,
                     (t - r[AT_END]) / BACK) for r in ended]
        coloured += [(PURPLE, (t - g[GU_T]) / BACK) for g in run.rows("gaveup", t - BACK, t + 1e-9)]
        outcomes = rare_rows_first(coloured, lambda o: o[0] != GREEN, OUTCOMES)  # a few failures among many deliveries

        sample = w.sample_at(run, t)
        busy = sample[SM_BUSY] if sample else 0
        stuck = w.stuck_on(run, t, sick(w.incident_at(run, t)))
        word, colour = _picture_state(w, run, variant, t)
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes,
            door_color=EXTRA2 if colour == EXTRA2 else None,
            fill=busy / WORKERS, gauge=EXTRA2 if busy > 0.8 * WORKERS else BLUE,
            outline=RED if stuck >= WORKERS // 2 else OUTLINE, state=(word, colour),
        )


LEAVES = 5  # endpoints drawn on the right: the one in trouble first, then the biggest customers
LEAVES_SMALL = 4  # ... on a short picture (under 20 rows), so each keeps room for its gauge


@adapts("webhook_delivery", "fanout")
class WebhookFanout(FanoutAdapter):
    """New events fly from the shop to the door (white); the dispatcher stands in the middle, its gauge the share
    of the 24 delivery workers busy, red (gauge and outline) while half of them or more are stuck on one
    endpoint. On the right, five of the 20 endpoints (four on a short screen): the one in trouble first (red
    while down or hanging, orange while slow, purple while it gets malformed events), then the biggest customers.
    Each endpoint's gauge is the workers busy with it (full at half the pool). Attempts fly to their endpoint,
    white the first, oranges for retries; an attempt still waiting for an answer stays near its endpoint, so
    workers stuck on a dead one pile up by it. Answers fly back green (deep orange delivered out of order); a
    failure dies red by the endpoint."""

    def frame(self, variant: str, t: float, users: int) -> FanoutFrame:
        from live.worlds.webhook_delivery import (
            AT_END, AT_ENDPOINT, AT_ID, AT_N, AT_OK, AT_START, EV_CREATED, EV_ID, SM_BUSY, attempt_colour, sick,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return FanoutFrame()
        lane = WebhookLanes(w).frame(variant, t, users)  # the events, the door and the outcomes, as in lanes
        flights = user_flights(every(just_sent(run, "events", t), FLIGHTS), t, EV_CREATED,
                               lambda e: (slot(e[EV_ID], users), WHITE, False))
        inc = w.incident_at(run, t)
        bad = sick(inc)
        most = LEAVES if users // GRID_COLS >= 20 else LEAVES_SMALL
        shown = ([bad] if bad >= 0 else []) + [e for e in range(ENDPOINTS) if e != bad][:most - (bad >= 0)]
        at = {e: k for k, e in enumerate(shown)}

        hops = []
        flying = [r for r in just_sent(run, "attempts", t) if r[AT_ENDPOINT] in at]
        for r in every(flying, FLIGHTS):
            hops.append((at[r[AT_ENDPOINT]], min((t - r[AT_START]) / FLY, 0.95), attempt_colour(r[AT_N]), False))
        in_flight = w.in_flight(run, t)
        waiting = [r for r in in_flight if r[AT_START] < t - FLY and r[AT_ENDPOINT] in at]
        for r in every(waiting, FLIGHTS):  # still waiting for an answer: it waits near its endpoint
            waited = t - r[AT_START]
            colour = EXTRA1 if waited < 1.0 else EXTRA2 if waited < 2.0 else EXTRA3
            hops.append((at[r[AT_ENDPOINT]], 0.6 + 0.35 * (r[AT_ID] * 0.618 % 1), colour, False))
        ended = [r for r in w.ended(run, t, BACK) if r[AT_ENDPOINT] in at]
        late = _ooo_ids(run, ended)
        failed = [r for r in ended if not r[AT_OK]]
        for r in every(failed, OUTCOMES) + every([r for r in ended if r[AT_OK]], OUTCOMES):
            p = (t - r[AT_END]) / BACK
            if r[AT_OK]:
                hops.append((at[r[AT_ENDPOINT]], p, EXTRA3 if r[AT_ID] in late else GREEN, True))
            else:
                hops.append((at[r[AT_ENDPOINT]], 0.95, RED, False))

        colours = _endpoint_colours(w, run, t)
        busy_on = [0] * ENDPOINTS
        for r in in_flight:
            busy_on[r[AT_ENDPOINT]] += 1
        leaves = []
        for e in shown:
            hurt = colours[e] != BLUE
            word = w.s("fan_endpoint", n=e + 1)  # its colour says what is wrong (the legend)
            stuck = busy_on[e] >= WORKERS // 2
            leaves.append(Leaf(label=(word, colours[e] if hurt else WHITE), fill=busy_on[e] / (WORKERS // 2),
                               gauge=RED if stuck else BLUE, outline=colours[e] if hurt else OUTLINE))
        sample = w.sample_at(run, t)
        busy = sample[SM_BUSY] if sample else 0
        stuck = w.stuck_on(run, t, bad) >= WORKERS // 2
        relay = Relay(label=(w.s("fan_dispatcher"), RED if stuck else OUTLINE), fill=busy / WORKERS,
                      gauge=RED if stuck else EXTRA2 if busy > 0.8 * WORKERS else BLUE,
                      outline=RED if stuck else OUTLINE)
        return FanoutFrame(users=lane.users, flights=flights, outcomes=lane.outcomes, closed=lane.closed,
                           door_color=lane.door_color, state=w.state(run, variant, t), relay=relay, leaves=leaves,
                           hops=hops)

"""The pictures for lab webhook_delivery: cluster (the dispatcher, four worker nodes of six workers each and
the 20 customer endpoints as nodes) and lanes (the events waiting on the left, the dispatcher as the door,
the worker pool as the server)."""

from __future__ import annotations

from labs.webhook_delivery.api import ENDPOINTS, WORKERS
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, SLOW, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

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
    """Each endpoint by its health right now: red dead (down or hanging), orange slow, purple while it gets
    malformed events, blue healthy."""
    from live.worlds.webhook_delivery import sick

    colours = [BLUE] * ENDPOINTS
    inc = w.incident_at(run, t)
    bad = sick(inc)
    if bad >= 0:
        colours[bad] = RED if inc.kind in ("down", "hang") else EXTRA2 if inc.kind == "slow" else PURPLE
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
                    for e in every(run.rows("events", t - FLY, t + 1e-9), FLIGHTS)]
        for r in every(run.rows("attempts", t - FLY, t + 1e-9), FLIGHTS):
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
        flying = run.rows("attempts", t - FLY, t + 1e-9)
        retries = every([r for r in flying if r[AT_N] > 1], FLIGHTS // 2)
        shown = retries + every([r for r in flying if r[AT_N] <= 1], FLIGHTS - len(retries))
        flights = [(slot(r[AT_ID], users), (t - r[AT_START]) / FLY, attempt_colour(r[AT_N]), r[AT_N] > 1)
                   for r in shown]
        ended = w.ended(run, t, BACK)
        late = _ooo_ids(run, ended)
        coloured = [(GREEN if r[AT_OK] and r[AT_ID] not in late else EXTRA3 if r[AT_OK] else RED,
                     (t - r[AT_END]) / BACK) for r in ended]
        coloured += [(PURPLE, (t - g[GU_T]) / BACK) for g in run.rows("gaveup", t - BACK, t + 1e-9)]
        rare = every([o for o in coloured if o[0] != GREEN], OUTCOMES)  # a few failures among many deliveries
        room = OUTCOMES - len(rare)
        outcomes = rare + (every([o for o in coloured if o[0] == GREEN], room) if room else [])

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

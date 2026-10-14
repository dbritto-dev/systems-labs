"""The pictures for lab saga: cluster (the orchestrator and the three services it calls) and lanes
(customers, the orchestrator as the door, the services as the server)."""

from __future__ import annotations

from labs.saga.api import DECLINED, OK
from labs.saga.scenario import DONE, ORPHAN, TIMEOUT_CAUSES
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, MUTED, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

CALLS_MAX = 40.0  # calls in flight at once that fill the services' gauge
RECENT = 2.0  # seconds a half-done order keeps the picture red
MAX_CALLS = 40  # calls drawn at once in the cluster picture


def _hit(world, variant: str, t: float) -> tuple[str | None, set[int]]:
    """The incident running at t (its kind) and the services it hits (0 payments, 1 stock, 2 shipping)."""
    inc = world.incident_at(variant, t)
    if inc is None:
        return None, set()
    hit = {"timeouts": {TIMEOUT_CAUSES.get(inc.cause, 2)}, "oom": {2}, "stockout": {1}, "shipping": {2}}
    return inc.kind, hit.get(inc.kind, set())


def _state(world, variant: str, t: float, orphans: bool) -> tuple[str, tuple[int, int, int]]:
    kind, _ = _hit(world, variant, t)
    if orphans:
        return world.s("state_orphans"), RED
    if world.down_at(variant, t):
        return world.s("state_down"), RED
    if kind in ("timeouts", "oom"):
        return world.s("state_timeouts"), EXTRA2
    if kind is not None:
        return world.s("state_failing"), EXTRA2
    return world.screen.STATES["healthy"], GREEN


@adapts("saga", "cluster")
class SagaCluster(ClusterAdapter):
    """The orchestrator (node 0, top left) and the services it calls: payments (1), stock (2) and
    shipping (3). New orders fly in from the customers (white). Each call flies from the orchestrator
    to its service: a step in white, a compensation in orange, a definite no in grey; a call that
    times out stops half way and fades (red). The orchestrator turns red while it is down; a service
    turns orange while an incident hits it and red while it holds something for an order left half
    done (money taken, items held or a courier booked for an order that will never complete).
    """

    ORCH = 0

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.saga import (
            CALL_OUTCOME, CALL_START, CALL_SVC, CALL_UNDO, ORD_END, ORD_HELD, ORD_START, ORD_STATUS,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights, drops = [], []
        for o in every(run.rows("orders", t - FLY, t + 1e-9), FLIGHTS):
            flights.append((-1, self.ORCH, (t - o[ORD_START]) / FLY, WHITE))
        for c in every(run.rows("calls", t - FLY, t + 1e-9), MAX_CALLS):
            p, dest = (t - c[CALL_START]) / FLY, c[CALL_SVC] + 1
            if c[CALL_OUTCOME] not in (OK, DECLINED):  # a timeout: the answer never comes back
                if p < 0.5:
                    flights.append((self.ORCH, dest, p, EXTRA2 if c[CALL_UNDO] else WHITE))
                else:
                    drops.append((self.ORCH, dest, (p - 0.5) * 2))
            else:
                colour = EXTRA2 if c[CALL_UNDO] else MUTED if c[CALL_OUTCOME] == DECLINED else WHITE
                flights.append((self.ORCH, dest, p, colour))
        span = run.max_dur.get("orders", 0.0)
        held = 0  # services holding something for an order left half done
        for o in run.rows("orders", t - RECENT - span, t + 1e-9):
            if o[ORD_STATUS] == ORPHAN and t - RECENT <= o[ORD_END] <= t:
                held |= o[ORD_HELD]
        _, hit = _hit(w, variant, t)
        nodes = [RED if w.down_at(variant, t) else BLUE]
        nodes += [RED if held >> i & 1 else EXTRA2 if i in hit else BLUE for i in range(3)]
        text, colour = _state(w, variant, t, bool(held))
        return ClusterFrame(nodes=nodes, flights=flights, drops=drops,
                            state=(w.s("pic_state", state=text), colour))


@adapts("saga", "lanes")
class SagaLanes(LaneAdapter):
    """Each order is a customer; it flies to the orchestrator (the door, closed in red while it is
    down) and waits while its saga runs: white, light orange after a timeout, orange while it is
    being compensated. It ends at the door green (completed), orange (rolled back) or red (left half
    done). The server is the three services; its gauge is the calls in flight."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.saga import (
            CALL_END, CALL_ORDER, CALL_OUTCOME, CALL_UNDO, ORD_END, ORD_ID, ORD_START, ORD_STATUS,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        shade: dict[int, tuple[int, int, int]] = {}  # order -> its colour while it waits
        for c in run.rows("calls", t - 6.0, t + 1e-9):
            if c[CALL_UNDO]:
                shade[c[CALL_ORDER]] = EXTRA2
            elif c[CALL_OUTCOME] not in (OK, DECLINED) and c[CALL_END] <= t:
                shade.setdefault(c[CALL_ORDER], EXTRA1)
        found = {slot(o[ORD_ID], users): (shade.get(o[ORD_ID], WHITE), True)
                 for o in run.active("orders", t, ORD_END)}
        flights = [(slot(o[ORD_ID], users), (t - o[ORD_START]) / FLY, WHITE, False)
                   for o in every(run.rows("orders", t - FLY, t + 1e-9), FLIGHTS)]
        span = run.max_dur.get("orders", 0.0)
        ended = [o for o in run.rows("orders", t - BACK - span, t + 1e-9) if t - BACK <= o[ORD_END] <= t]
        bad = [o for o in ended if o[ORD_STATUS] == ORPHAN]
        shown = every(bad, OUTCOMES)
        shown += every([o for o in ended if o[ORD_STATUS] != ORPHAN], OUTCOMES - len(shown)) if len(shown) < OUTCOMES else []

        def colour(o: tuple):
            return RED if o[ORD_STATUS] == ORPHAN else GREEN if o[ORD_STATUS] == DONE else EXTRA2

        outcomes = [(colour(o), (t - o[ORD_END]) / BACK) for o in shown]
        recent = run.rows("orders", t - RECENT - span, t + 1e-9)
        orphans = any(o[ORD_STATUS] == ORPHAN and t - RECENT <= o[ORD_END] <= t for o in recent)
        in_flight = run.active("calls", t, CALL_END)
        undoing = any(c[CALL_UNDO] for c in in_flight)
        down = w.down_at(variant, t)
        state = _state(w, variant, t, orphans)
        _, hit = _hit(w, variant, t)
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes, closed=down,
            door_color=RED if down else None,
            fill=len(in_flight) / CALLS_MAX, gauge=EXTRA2 if undoing else BLUE,
            outline=RED if orphans else EXTRA2 if hit else OUTLINE, state=state,
        )


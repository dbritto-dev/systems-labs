"""The pictures for lab saga_orchestration: cluster (the orchestrator and the three services it calls) and lanes
(customers, the orchestrator as the door, the services as the server)."""

from __future__ import annotations

from labs.saga_orchestration.api import DECLINED, OK
from labs.saga_orchestration.scenario import DONE, ORPHAN, TIMEOUT_CAUSES
from live.adapters.common import FLIGHTS, FLY, every, just_ended, just_sent, user_flights, user_outcomes
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, MUTED, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_fanout import FanoutAdapter, FanoutFrame, Leaf
from live.views.lanes_relay import Relay

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


@adapts("saga_orchestration", "cluster")
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
        from live.worlds.saga_orchestration import (
            CALL_OUTCOME, CALL_START, CALL_SVC, CALL_UNDO, ORD_END, ORD_HELD, ORD_START, ORD_STATUS,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights, drops = [], []
        for o in every(just_sent(run, "orders", t), FLIGHTS):
            flights.append((-1, self.ORCH, (t - o[ORD_START]) / FLY, WHITE))
        for c in every(just_sent(run, "calls", t), MAX_CALLS):
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


@adapts("saga_orchestration", "lanes")
class SagaLanes(LaneAdapter):
    """Each order is a customer; it flies to the orchestrator (the door, closed in red while it is
    down) and waits while its saga runs: white, light orange after a timeout, orange while it is
    being compensated. It ends at the door green (completed), orange (rolled back) or red (left half
    done). The server is the three services; its gauge is the calls in flight."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.saga_orchestration import (
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
        flights = user_flights(every(just_sent(run, "orders", t), FLIGHTS), t, ORD_START,
                               lambda o: (slot(o[ORD_ID], users), WHITE, False))
        span = run.max_dur.get("orders", 0.0)
        ended = just_ended(run, "orders", ORD_END, t)

        def colour(o: tuple):
            return RED if o[ORD_STATUS] == ORPHAN else GREEN if o[ORD_STATUS] == DONE else EXTRA2

        outcomes = user_outcomes(ended, t, ORD_END, colour, rare=lambda o: o[ORD_STATUS] == ORPHAN)
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



@adapts("saga_orchestration", "fanout")
class SagaFanout(FanoutAdapter):
    """Orders arrive at the orchestrator (the door, shut in red while it is down; the relay in the middle,
    its gauge the sagas still running) and it calls three services on the right: payments, stock and
    shipping, each with its own gauge (its calls in flight). A step flies white, a compensation orange, a
    definite no grey; a call that times out stops half way, red. A service turns orange while an incident
    hits it and red while it holds money, items or a courier for an order left half done."""

    def frame(self, variant: str, t: float, users: int) -> FanoutFrame:
        from live.worlds.saga_orchestration import (
            CALL_END, CALL_OUTCOME, CALL_START, CALL_SVC, CALL_UNDO, ORD_END, ORD_HELD, ORD_STATUS,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return FanoutFrame()
        lane = SagaLanes(w).frame(variant, t, users)  # the users, the door and the outcomes, as in lanes
        hops = []
        for c in every(just_sent(run, "calls", t), MAX_CALLS):
            p = (t - c[CALL_START]) / FLY
            if c[CALL_OUTCOME] not in (OK, DECLINED):  # a timeout: it never gets an answer
                hops.append((c[CALL_SVC], min(p, 0.5), RED if p >= 0.5 else EXTRA2 if c[CALL_UNDO] else WHITE, False))
            else:
                hops.append((c[CALL_SVC], p, EXTRA2 if c[CALL_UNDO] else MUTED if c[CALL_OUTCOME] == DECLINED else WHITE,
                             False))
        span = run.max_dur.get("orders", 0.0)
        held = 0
        for o in run.rows("orders", t - RECENT - span, t + 1e-9):
            if o[ORD_STATUS] == ORPHAN and t - RECENT <= o[ORD_END] <= t:
                held |= o[ORD_HELD]
        _, hit = _hit(w, variant, t)
        in_flight = run.active("calls", t, CALL_END)
        leaves = []
        for i, key in enumerate(("fan_payments", "fan_stock", "fan_shipping")):
            mine = [c for c in in_flight if c[CALL_SVC] == i]
            colour = RED if held >> i & 1 else EXTRA2 if i in hit else OUTLINE
            leaves.append(Leaf(label=(w.s(key), RED if held >> i & 1 else EXTRA2 if i in hit else WHITE),
                               short=w.s(f"{key}_short"), tiny=w.s(f"{key}_tiny"),
                               fill=len(mine) / (CALLS_MAX / 3),
                               gauge=EXTRA2 if any(c[CALL_UNDO] for c in mine) else BLUE, outline=colour))
        down = w.down_at(variant, t)
        running = len(run.active("orders", t, ORD_END))
        relay = Relay(label=(w.s("fan_orchestrator"), RED if down else OUTLINE), fill=running / CALLS_MAX,
                      gauge=BLUE, outline=RED if down else OUTLINE)
        return FanoutFrame(users=lane.users, flights=lane.flights, outcomes=lane.outcomes, closed=lane.closed,
                           door_color=lane.door_color, state=lane.state, relay=relay, leaves=leaves, hops=hops,
                           vertical=True)  # payments, stock, shipping: read top to bottom

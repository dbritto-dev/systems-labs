"""The pictures for lab load_balancing: cluster (the 4 balancers on the top row, the 8 servers below,
every request flying from a balancer to the server it picked) and lanes (users → the balancers as the
door → the fleet of servers)."""

from __future__ import annotations

from labs.load_balancing.scenario import BALANCERS, WORKERS
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, client_lanes, every, op_id
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

QUEUE_FULL = 4 * WORKERS  # requests in flight on one server that fill the gauge


def _load_colour(n: int):
    """A server by how many requests it has in flight: blue while its workers keep up, then orange."""
    return BLUE if n <= WORKERS else EXTRA1 if n <= 2 * WORKERS else EXTRA2 if n <= QUEUE_FULL else EXTRA3


def _state(w, run, t: float, sick: int, timeouts: bool):
    words = w.screen.STATES
    if sick < 0:
        return (words["overloaded"], RED) if timeouts else (words["healthy"], GREEN)
    key, colour = ("overloaded", RED) if timeouts else ("degraded", PURPLE)
    return w.s("state_sick", state=words[key], server=sick), colour


@adapts("load_balancing", "cluster")
class LoadBalancingCluster(ClusterAdapter):
    """The 4 balancers (top row) and the 8 servers. A request flies from the users to a balancer, then on
    to the server it picked (purple when that is the slow server); requests waiting long sit by their
    server, orange. A server is coloured by the requests it has in flight; the slow one is purple. A
    balancer turns orange while it herds (sends most of its requests to one server); timeouts die in red
    on the way to their server."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.load_balancing import HERD, REQ_BALANCER, REQ_END, REQ_OK, REQ_SERVER, REQ_SICK, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        sick = w.sick_at(run, t)
        loads = w.loads_at(run, t)
        herds = w.herding(run, t)
        balancers = [EXTRA2 if h >= HERD else BLUE for h in herds]
        servers = [PURPLE if i == sick else _load_colour(n) for i, n in enumerate(loads)]

        flights = []
        for r in every(run.rows("requests", t - FLY, t + 1e-9), 2 * FLIGHTS):
            p = (t - r[REQ_START]) / FLY
            if p < 0.5:
                flights.append((-1, r[REQ_BALANCER], 2 * p, WHITE))
            else:
                flights.append((r[REQ_BALANCER], BALANCERS + r[REQ_SERVER], 2 * p - 1,
                                PURPLE if r[REQ_SICK] else WHITE))
        for r in every([r for r in run.active("requests", t, REQ_END) if r[REQ_START] < t - FLY], FLIGHTS):
            waited = t - r[REQ_START]  # still waiting: it sits by its server
            colour = EXTRA1 if waited < 0.5 else EXTRA2 if waited < 0.8 else EXTRA3
            flights.append((r[REQ_BALANCER], BALANCERS + r[REQ_SERVER], 0.9, colour))

        span = run.max_dur.get("requests", 0.0)
        failed = [r for r in run.rows("requests", t - BACK - span, t + 1e-9)
                  if t - BACK <= r[REQ_END] <= t and not r[REQ_OK]]
        drops = [(r[REQ_BALANCER], BALANCERS + r[REQ_SERVER], (t - r[REQ_END]) / BACK)
                 for r in every(failed, OUTCOMES)]
        text, colour = _state(w, run, t, sick, bool(failed))
        return ClusterFrame(nodes=balancers + servers, flights=flights, drops=drops,
                            state=(f"{text}   {w.s('topology')}", colour))


@adapts("load_balancing", "lanes")
class LoadBalancingLanes(LaneAdapter):
    """Users wait for an answer (orange the longer they wait); requests fly to the door, which is the 4
    balancers (orange while one herds, shut in red while requests time out); requests to the slow
    server fly big and purple. The server is the fleet: its gauge is the busiest server's queue, its
    outline purple while one server is slow."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.load_balancing import HERD, REQ_END, REQ_OK, REQ_SICK, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, _, outcomes = client_lanes(run, t, users, "requests", REQ_START, REQ_END,
                                            colour=lambda r: GREEN if r[REQ_OK] else RED, rare_first=True)
        flying = run.rows("requests", t - FLY, t + 1e-9)
        shown = every([r for r in flying if r[REQ_SICK]], FLIGHTS // 2)
        shown += every([r for r in flying if not r[REQ_SICK]], FLIGHTS - len(shown))
        flights = [(slot(op_id(r[REQ_START]), users), (t - r[REQ_START]) / FLY,
                    PURPLE if r[REQ_SICK] else WHITE, bool(r[REQ_SICK])) for r in shown]

        sick = w.sick_at(run, t)
        busiest = max(w.loads_at(run, t))
        span = run.max_dur.get("requests", 0.0)
        timeouts = any(t - BACK <= r[REQ_END] <= t and not r[REQ_OK]
                       for r in run.rows("requests", t - BACK - span, t + 1e-9))
        herding = max(w.herding(run, t)) >= HERD
        state = _state(w, run, t, sick, timeouts)
        gauge = RED if busiest >= QUEUE_FULL else EXTRA2 if busiest > 2 * WORKERS else BLUE
        return LaneFrame(
            users=waiting, flights=flights, outcomes=outcomes, closed=timeouts,
            door_color=EXTRA2 if herding and not timeouts else None,
            fill=busiest / QUEUE_FULL, gauge=gauge, outline=PURPLE if sick >= 0 else OUTLINE, state=state,
        )

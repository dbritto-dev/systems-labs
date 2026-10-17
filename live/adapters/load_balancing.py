"""The pictures for lab load_balancing: cluster (the 4 balancers on the top row, the 8 servers below,
every request flying from a balancer to the server it picked), lanes (users → the balancers as the
door → the fleet of servers), relay (the balancers as a server of their own, the fleet as one) and
fan-out (the balancers in the middle, each of the 8 servers on its own on the right)."""

from __future__ import annotations

from labs.load_balancing.scenario import BALANCERS, WORKERS
from live.adapters.common import (
    BACK, FLIGHTS, FLY, OUTCOMES, client_lanes, every, just_ended, just_sent, op_id, rare_rows_first, user_flights,
)
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_fanout import FanoutAdapter, FanoutFrame, Leaf
from live.views.lanes_relay import Relay, RelayAdapter, RelayFrame

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
        for r in every(just_sent(run, "requests", t), 2 * FLIGHTS):
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

        failed = [r for r in just_ended(run, "requests", REQ_END, t) if not r[REQ_OK]]
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
        flying = just_sent(run, "requests", t)
        shown = rare_rows_first(flying, lambda r: r[REQ_SICK], FLIGHTS, FLIGHTS // 2)
        flights = user_flights(shown, t, REQ_START, lambda r: (
            slot(op_id(r[REQ_START]), users), PURPLE if r[REQ_SICK] else WHITE, bool(r[REQ_SICK])))

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


@adapts("load_balancing", "relay")
class LoadBalancingRelay(RelayAdapter):
    """The lanes picture with the balancers as a server of their own: users → the door → the 4 balancers →
    the fleet of servers. The balancers' gauge is how much one of them herds (sends most of its requests to
    one server), orange when it does. Requests fly user → door, then balancer → server; those to the slow
    server fly big and purple. The server on the right is the fleet, as in the lanes picture."""

    def frame(self, variant: str, t: float, users: int) -> RelayFrame:
        from live.worlds.load_balancing import HERD, REQ_END, REQ_OK, REQ_SICK, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return RelayFrame()
        waiting, _, outcomes = client_lanes(run, t, users, "requests", REQ_START, REQ_END,
                                            colour=lambda r: GREEN if r[REQ_OK] else RED, rare_first=True)
        flying = just_sent(run, "requests", t)
        shown = rare_rows_first(flying, lambda r: r[REQ_SICK], FLIGHTS, FLIGHTS // 2)
        flights, hops = [], []  # the first half of the way: user → door; the second: balancer → server
        for r in shown:
            p = (t - r[REQ_START]) / FLY
            if p < 0.5:
                flights.append((slot(op_id(r[REQ_START]), users), 2 * p, WHITE, False))
            else:
                hops.append((2 * p - 1, PURPLE if r[REQ_SICK] else WHITE, bool(r[REQ_SICK])))

        sick = w.sick_at(run, t)
        busiest = max(w.loads_at(run, t))
        span = run.max_dur.get("requests", 0.0)
        timeouts = any(t - BACK <= r[REQ_END] <= t and not r[REQ_OK]
                       for r in run.rows("requests", t - BACK - span, t + 1e-9))
        herd = max(w.herding(run, t))
        herding = herd >= HERD
        relay = Relay(label=(w.s("lanes_balancers"), EXTRA2 if herding else OUTLINE), fill=herd,
                      gauge=EXTRA2 if herding else BLUE, outline=EXTRA2 if herding else OUTLINE)
        gauge = RED if busiest >= QUEUE_FULL else EXTRA2 if busiest > 2 * WORKERS else BLUE
        return RelayFrame(
            users=waiting, flights=flights, outcomes=outcomes, closed=timeouts,
            fill=busiest / QUEUE_FULL, gauge=gauge, outline=PURPLE if sick >= 0 else OUTLINE,
            state=_state(w, run, t, sick, timeouts), relay=relay, hops=hops,
        )


@adapts("load_balancing", "fanout")
class LoadBalancingFanout(FanoutAdapter):
    """The relay picture with the fleet opened up: users → the door → the 4 balancers (their gauge is how much
    one of them herds, orange when it does) → each of the 8 servers on its own, s0 ... s7, its gauge its queue
    (requests in flight against 4x its workers: blue while its workers keep up, then oranges, red full), the
    slow one purple ("s2 slow"). Each request flies from the balancers to the very server it was sent to,
    white (big and purple to the slow one); one still waiting sits by its server, orange the longer it waits;
    a timeout comes back from its server in red. Herding shows as most requests flying to one server."""

    def frame(self, variant: str, t: float, users: int) -> FanoutFrame:
        from live.worlds.load_balancing import REQ_END, REQ_OK, REQ_SERVER, REQ_SICK, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return FanoutFrame()
        relay = LoadBalancingRelay(w).frame(variant, t, users)  # the users, the door, the balancers, the state
        hops = []
        for r in every([r for r in just_sent(run, "requests", t) if t - r[REQ_START] >= FLY / 2], 2 * FLIGHTS):
            hops.append((r[REQ_SERVER], 2 * (t - r[REQ_START]) / FLY - 1, PURPLE if r[REQ_SICK] else WHITE, False))
        for r in every([r for r in run.active("requests", t, REQ_END) if r[REQ_START] < t - FLY], FLIGHTS):
            waited = t - r[REQ_START]  # still waiting: it sits by its server
            hops.append((r[REQ_SERVER], 0.92, EXTRA1 if waited < 0.5 else EXTRA2 if waited < 0.8 else EXTRA3, False))
        failed = [r for r in just_ended(run, "requests", REQ_END, t) if not r[REQ_OK]]
        for r in every(failed, OUTCOMES):  # a timeout: back from its server, red
            hops.append((r[REQ_SERVER], (t - r[REQ_END]) / BACK, RED, True))
        sick = w.sick_at(run, t)
        leaves = []
        for i, n in enumerate(w.loads_at(run, t)):
            fill = min(1.0, n / QUEUE_FULL)
            gauge = RED if n >= QUEUE_FULL else _load_colour(n)
            if i == sick:
                leaves.append(Leaf(label=(w.s("fan_slow", n=i), PURPLE), fill=fill, gauge=gauge, outline=PURPLE))
            else:
                leaves.append(Leaf(label=(w.s("fan_server", n=i), WHITE), fill=fill, gauge=gauge,
                                   outline=RED if n >= QUEUE_FULL else OUTLINE))
        return FanoutFrame(users=relay.users, flights=relay.flights, outcomes=relay.outcomes, closed=relay.closed,
                           door_color=relay.door_color, state=relay.state, relay=relay.relay, leaves=leaves,
                           hops=hops)

"""The pictures for lab graceful_shutdown: lanes (users → the load balancer as the door → the fleet of 6
instances) and cluster (the 3 balancer nodes on the top row, the 6 instance slots below, every request
flying from a balancer node to the instance it reaches) and relay (users → the door → the load balancer →
the fleet)."""

from __future__ import annotations

from labs.graceful_shutdown.scenario import DRAINING, INSTANCES, LB_NODES, LEAVING, REFUSING, SERVING, STARTING
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, client_lanes, every, op_id
from live.canvas import BLUE, EXTRA2, GREEN, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_relay import Relay, RelayAdapter, RelayFrame


def _colour(r) -> tuple[int, int, int]:
    """A request in flight: red when it failed, orange when it went to an instance that got SIGTERM."""
    from live.worlds.graceful_shutdown import REQ_OK, REQ_OLD

    return RED if not r[REQ_OK] else EXTRA2 if r[REQ_OLD] else WHITE


def _state(w, run, t: float) -> tuple[str, tuple[int, int, int]]:
    """The words under the server or the grid: the slot worth naming and how many instances serve."""
    from live.worlds.graceful_shutdown import IN_SLOT

    _, serving, _ = w.fleet(run, t)
    n = dict(n=serving, of=INSTANCES)
    cut = w.cut_at(run, t, 1.0)
    if cut:
        return w.s("state_cut", slot=cut[-1][IN_SLOT], **n), RED
    where, state = w.focus(run, t)
    if state == REFUSING:
        return w.s("state_refusing", slot=where, **n), RED
    if state == LEAVING:
        return w.s("state_leaving", slot=where, **n), EXTRA2
    if state == DRAINING:
        return w.s("state_draining", slot=where, **n), EXTRA2
    if state == STARTING:
        return w.s("state_starting", slot=where, **n), PURPLE
    return w.s("state_ok", **n), GREEN


def _failures(run, t: float) -> list[tuple]:
    """Requests that failed in the last BACK seconds."""
    from live.worlds.graceful_shutdown import REQ_END, REQ_OK

    span = run.max_dur.get("requests", 0.0)
    return [r for r in run.rows("requests", t - BACK - span, t + 1e-9)
            if t - BACK <= r[REQ_END] <= t and not r[REQ_OK]]


@adapts("graceful_shutdown", "lanes")
class GracefulShutdownLanes(LaneAdapter):
    """Users wait for an answer (orange the longer they wait); requests fly to the door, which is the load
    balancer: orange while it still holds an instance that got SIGTERM, shut in red while requests fail.
    Requests that reach an old instance fly orange, failed ones big and red. The server is the fleet: its
    gauge is how many of the 6 instances serve (blue 6, orange 5, red fewer), its outline orange while one
    shuts down."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.graceful_shutdown import REQ_END, REQ_OK, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, _, outcomes = client_lanes(run, t, users, "requests", REQ_START, REQ_END,
                                            colour=lambda r: GREEN if r[REQ_OK] else RED, rare_first=True)
        flying = run.rows("requests", t - FLY, t + 1e-9)
        shown = every([r for r in flying if not r[REQ_OK]], FLIGHTS // 2)
        shown += every([r for r in flying if r[REQ_OK]], FLIGHTS - len(shown))
        flights = [(slot(op_id(r[REQ_START]), users), (t - r[REQ_START]) / FLY, _colour(r), not r[REQ_OK])
                   for r in shown]
        states, serving, _ = w.fleet(run, t)
        closing = any(s in (LEAVING, DRAINING, REFUSING) for s in states)
        failing = bool(_failures(run, t))
        gauge = BLUE if serving >= INSTANCES else EXTRA2 if serving >= INSTANCES - 1 else RED
        return LaneFrame(
            users=waiting, flights=flights, outcomes=outcomes, closed=failing,
            door_color=EXTRA2 if closing and not failing else None,
            fill=serving / INSTANCES, gauge=gauge, outline=EXTRA2 if closing else OUTLINE,
            state=_state(w, run, t),
        )


@adapts("graceful_shutdown", "cluster")
class GracefulShutdownCluster(ClusterAdapter):
    """The 3 balancer nodes (top row) and the 6 instance slots. A request flies from the users to a balancer
    node, then on to its instance (orange when that one got SIGTERM). An instance is blue while it serves,
    purple while it starts, orange while it shuts down, red while a balancer node still sends it new
    connections it refuses, grey once it is gone. Refused and cut requests die in red; a balancer node that
    just sent one turns red too."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.graceful_shutdown import (
            REQ_END, REQ_LB, REQ_OK, REQ_OUT, REQ_SLOT, REQ_START, STATE_COLOURS,
        )
        from labs.graceful_shutdown.scenario import CUT

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        states, _, _ = w.fleet(run, t)
        failed = _failures(run, t)
        bad_nodes = {r[REQ_LB] for r in failed}
        nodes = [RED if n in bad_nodes else BLUE for n in range(LB_NODES)]
        nodes += [STATE_COLOURS[s] for s in states]

        flights = []
        for r in every(run.rows("requests", t - FLY, t + 1e-9), 2 * FLIGHTS):
            if r[REQ_SLOT] < 0:
                continue
            p = (t - r[REQ_START]) / FLY
            if p < 0.5:
                flights.append((-1, r[REQ_LB], 2 * p, WHITE))
            elif r[REQ_OK] or r[REQ_OUT] == CUT:
                flights.append((r[REQ_LB], LB_NODES + r[REQ_SLOT], 2 * p - 1, _colour(r)))
        drops = [(r[REQ_LB], LB_NODES + r[REQ_SLOT], (t - r[REQ_END]) / BACK)
                 for r in every([r for r in failed if r[REQ_SLOT] >= 0], OUTCOMES)]
        text, colour = _state(w, run, t)
        return ClusterFrame(nodes=nodes, flights=flights, drops=drops,
                            state=(f"{text}   {w.s('topology')}", colour))


@adapts("graceful_shutdown", "relay")
class GracefulShutdownRelay(RelayAdapter):
    """The lanes picture with the load balancer as a server of its own: users → the door → the load balancer
    → the fleet of 6 instances (as in the lanes picture). The balancer's gauge is its rotation: the share of
    the 6 slots it sends new connections to. It is blue while all of them serve, orange while it still sends
    to an instance that got SIGTERM (it has not noticed yet), red while it sends to one that no longer
    listens (those connections are refused); its outline is the same colour. Under it: its rotation, as
    instances routed to / 6. Requests fly user → door, then balancer → instance: orange to an instance that got
    SIGTERM, big and red when they failed (refused, or cut by a SIGKILL). Under the fleet: the slot worth
    naming (REFUSING s0), its gauge the instances serving."""

    def frame(self, variant: str, t: float, users: int) -> RelayFrame:
        from live.worlds.graceful_shutdown import REQ_OK, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return RelayFrame()
        lane = GracefulShutdownLanes(w).frame(variant, t, users)  # users, outcomes and the fleet
        flying = run.rows("requests", t - FLY, t + 1e-9)
        shown = every([r for r in flying if not r[REQ_OK]], FLIGHTS // 2)
        shown += every([r for r in flying if r[REQ_OK]], FLIGHTS - len(shown))
        flights, hops = [], []  # the first half of the way: user → door; the second: balancer → instance
        for r in shown:
            p = (t - r[REQ_START]) / FLY
            if p < 0.5:
                flights.append((slot(op_id(r[REQ_START]), users), 2 * p, WHITE, False))
            else:
                hops.append((2 * p - 1, _colour(r), not r[REQ_OK]))

        states, _, _ = w.fleet(run, t)
        routed = sum(1 for s in states if s in (SERVING, LEAVING, REFUSING))
        colour = RED if REFUSING in states else EXTRA2 if LEAVING in states else BLUE
        relay = Relay(label=(w.s("relay_lb", n=routed, of=INSTANCES), OUTLINE if colour == BLUE else colour),
                      fill=routed / INSTANCES, gauge=colour, outline=OUTLINE if colour == BLUE else colour)
        text, col = lane.state  # "REFUSING s0 · 5/6": the count is the fleet's gauge, and the words must fit
        return RelayFrame(
            users=lane.users, flights=flights, outcomes=lane.outcomes, closed=lane.closed,
            fill=lane.fill, gauge=lane.gauge, outline=lane.outline, state=(text.split(" · ")[0], col),
            relay=relay, hops=hops,
        )

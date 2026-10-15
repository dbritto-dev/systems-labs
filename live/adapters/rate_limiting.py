"""The pictures for lab rate_limiting: lanes (the door is the rate limiter, the server is the backend),
cluster (clients -> limiter -> backend) and relay (users -> the door -> the gateway -> the API server)."""

from __future__ import annotations

from labs.rate_limiting.scenario import FAILED, LIMITED, QUEUE, SERVED, WORKERS
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_relay import Relay, RelayAdapter, RelayFrame


@adapts("rate_limiting", "lanes")
class RateLimitLanes(LaneAdapter):
    """Normal requests are white, a flooding client's orange; the door shuts on a flood it turns away."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.rate_limiting import REQ_END, REQ_FLOOD, REQ_ID, REQ_OUTCOME, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        found = {slot(r[REQ_ID], users): (EXTRA2 if r[REQ_FLOOD] else WHITE, True)
                 for r in run.active("requests", t, REQ_END) if r[REQ_OUTCOME] != LIMITED}

        flying = run.rows("requests", t - FLY, t + 1e-9)
        flights = [(slot(r[REQ_ID], users), (t - r[REQ_START]) / FLY, EXTRA2 if r[REQ_FLOOD] else WHITE,
                    bool(r[REQ_FLOOD])) for r in every(flying, FLIGHTS)]
        ended = [r for r in run.rows("requests", t - BACK - run.max_dur.get("requests", 0.0), t + 1e-9)
                 if t - BACK <= r[REQ_END] <= t]
        colour = {SERVED: GREEN, LIMITED: EXTRA3, FAILED: RED}
        outcomes = [(colour[r[REQ_OUTCOME]], (t - r[REQ_END]) / BACK) for r in every(ended, OUTCOMES)]

        last = run.rows("requests", t - 1, t)
        limited = sum(1 for r in last if r[REQ_OUTCOME] == LIMITED)
        rejecting = bool(last) and limited / len(last) > 0.3  # turning a flood away
        at_backend = w.backend_at(run, t)
        overloaded = any(r[REQ_OUTCOME] == FAILED for r in last)
        words = w.screen.STATES
        if overloaded:
            state, gauge, outline = (words["overloaded"], RED), RED, RED
        elif at_backend > WORKERS:
            state, gauge, outline = (words["busy"], EXTRA2), EXTRA2, EXTRA2
        else:
            state, gauge, outline = (words["healthy"], GREEN), BLUE, OUTLINE
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes, closed=rejecting,
            door_color=EXTRA3 if rejecting else None,
            fill=at_backend / (WORKERS + QUEUE), gauge=gauge, outline=outline, state=state,
        )


@adapts("rate_limiting", "cluster")
class RateLimitCluster(ClusterAdapter):
    """The topology: clients -> the rate limiter (node 0) -> the backend (node 1). Normal requests fly
    white, a flooding client's orange; requests the limiter turns away die red before it, 503s from
    the backend die red between the two."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.rate_limiting import REQ_END, REQ_FLOOD, REQ_OUTCOME, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights = []
        flying = run.rows("requests", t - FLY, t + 1e-9)
        shown = every([r for r in flying if r[REQ_OUTCOME] == FAILED], FLIGHTS // 3)  # the 503s first
        shown += every([r for r in flying if r[REQ_OUTCOME] != FAILED], FLIGHTS - len(shown))
        for r in shown:
            p = (t - r[REQ_START]) / FLY
            colour = EXTRA2 if r[REQ_FLOOD] else WHITE
            if p < 0.5:
                flights.append((-1, 0, p * 2, colour))
            elif r[REQ_OUTCOME] != LIMITED:  # let through
                flights.append((0, 1, (p - 0.5) * 2, colour))
        ended = [r for r in run.rows("requests", t - BACK - run.max_dur.get("requests", 0.0), t + 1e-9)
                 if t - BACK <= r[REQ_END] <= t and r[REQ_OUTCOME] in (LIMITED, FAILED)]
        drops = [((-1, 0) if r[REQ_OUTCOME] == LIMITED else (0, 1)) + ((t - r[REQ_END]) / BACK,)
                 for r in every(ended, OUTCOMES)]
        last = run.rows("requests", t - 1, t)
        limited = sum(1 for r in last if r[REQ_OUTCOME] == LIMITED)
        rejecting = bool(last) and limited / len(last) > 0.3
        at_backend = w.backend_at(run, t)
        words = w.screen.STATES
        if any(r[REQ_OUTCOME] == FAILED for r in last):
            backend, state = RED, (words["overloaded"], RED)
        elif at_backend > WORKERS:
            backend, state = EXTRA2, (words["busy"], EXTRA2)
        else:
            backend, state = BLUE, (words["healthy"], GREEN)
        return ClusterFrame(nodes=[EXTRA3 if rejecting else BLUE, backend], flights=flights, drops=drops,
                            state=(w.s("pic_state", state=state[0]), state[1]))


@adapts("rate_limiting", "relay")
class RateLimitRelay(RelayAdapter):
    """The lanes picture with the limiter as a server of its own: users → the door → the gateway (the rate
    limiter) → the API server (the backend, as in the lanes picture). The gateway's gauge is how full the
    limits are: the requests the busiest client got through in the last second, against its limit (a full
    gauge is a client using all its tokens). It is blue while nobody is refused, dark orange (the 429s'
    colour) while it refuses requests, red while a client gets through well over its limit (nothing holds
    it back); its outline is the same colour. Under it: "gateway", or the 429s it sent in the last second.
    Requests fly user → door (a flooding client's orange); only those the gateway lets through fly on to the
    API server, the backend's 503s big and red. Refusals (429) fade at the door in their colour, with the
    other answers; the door shuts in red while the backend fails."""

    def frame(self, variant: str, t: float, users: int) -> RelayFrame:
        from labs.rate_limiting.lab import CLIENT_RATE, PEAK_MAX
        from live.worlds.rate_limiting import REQ_CLIENT, REQ_FLOOD, REQ_ID, REQ_OUTCOME, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return RelayFrame()
        lane = RateLimitLanes(w).frame(variant, t, users)  # users, outcomes and the backend
        flights, hops = [], []  # the first half of the way: user → door; the second: gateway → API server
        flying = run.rows("requests", t - FLY, t + 1e-9)
        shown = every([r for r in flying if r[REQ_OUTCOME] == FAILED], FLIGHTS // 3)  # the 503s first
        shown += every([r for r in flying if r[REQ_OUTCOME] != FAILED], FLIGHTS - len(shown))
        for r in shown:
            p = (t - r[REQ_START]) / FLY
            colour = EXTRA2 if r[REQ_FLOOD] else WHITE
            if p < 0.5:
                flights.append((slot(r[REQ_ID], users), 2 * p, colour, bool(r[REQ_FLOOD])))
            elif r[REQ_OUTCOME] == FAILED:  # the backend turned it away (503)
                hops.append((2 * p - 1, RED, True))
            elif r[REQ_OUTCOME] != LIMITED:  # the gateway let it through
                hops.append((2 * p - 1, colour, bool(r[REQ_FLOOD])))

        last = run.rows("requests", t - 1, t)
        through: dict[int, int] = {}
        for r in last:
            if r[REQ_OUTCOME] != LIMITED:
                through[r[REQ_CLIENT]] = through.get(r[REQ_CLIENT], 0) + 1
        used = max(through.values(), default=0) / CLIENT_RATE  # the busiest client's tokens used
        limited = sum(1 for r in last if r[REQ_OUTCOME] == LIMITED)
        if used > PEAK_MAX:
            colour = RED
        elif limited:
            colour = EXTRA3
        else:
            colour = BLUE
        label = w.s("relay_refused", n=limited) if limited else w.s("relay_gateway")
        relay = Relay(label=(label, OUTLINE if colour == BLUE else colour),
                      fill=min(1.0, used), gauge=colour, outline=OUTLINE if colour == BLUE else colour)
        return RelayFrame(
            users=lane.users, flights=flights, outcomes=lane.outcomes, closed=lane.gauge == RED,
            fill=lane.fill, gauge=lane.gauge, outline=lane.outline, state=lane.state, relay=relay, hops=hops,
        )

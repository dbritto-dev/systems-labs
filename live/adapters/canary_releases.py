"""The pictures for lab canary_releases: lanes (users → the router as the door, purple while it splits the
traffic → the fleet as one server whose gauge is the new build's share) and cluster (one node per instance:
blue on the live build, purple on the new one; red or orange while the build they run hurts requests;
requests fly to the instance that got them, purple ones to the canary) and relay (users → the door → the
router → the fleet)."""

from __future__ import annotations

from labs.canary_releases.scenario import FLEET
from live.adapters.common import (
    BACK, FLIGHTS, FLY, OUTCOMES, client_lanes, every, just_ended, just_sent, op_id, user_flights,
)
from live.canvas import GREEN, RED, RGB, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_relay import Relay, RelayAdapter, RelayFrame

CLOSED = 0.05  # the door shuts (solid red) when this share of the last second's requests failed
HURTING = 3  # requests hurt in the last 2 s that turn the server's outline red


def _now(w, run, t: float) -> dict:
    """What the router is doing at t: live and new versions, the canary's share, whether the live build is
    a bad one, and whether a rollback just happened."""
    from live.worlds.canary_releases import E_T, E_VERSION, E_WHAT, ROLLED_BACK, ROLLBACK, bad, router, version_of

    live, new, weight, last = router(run, t)
    inc = w.release_at(run, t)
    back = last is not None and last[E_WHAT] == ROLLBACK and last[E_T] > t - ROLLED_BACK
    return {"live": live, "new": new, "weight": weight, "back": last[E_VERSION] if back else None,
            "bad_live": inc is not None and bad(inc.kind) and live == version_of(inc)}


def _state(w, now: dict) -> tuple[str, RGB]:
    from live.worlds.canary_releases import CANARY_C, LIVE_C

    if now["bad_live"]:
        return w.s("state_bad", v=now["live"]), RED
    if now["new"] is not None:
        return w.s("state_canary", v=now["new"], w=now["weight"]), CANARY_C
    if now["back"] is not None:
        return w.s("state_back", v=now["back"]), GREEN
    return w.s("state_live", v=now["live"]), LIVE_C


def _outcome(r) -> RGB:
    from live.worlds.canary_releases import FAILED_C, REQ_OK, REQ_SLOW, SLOW_C

    return FAILED_C if not r[REQ_OK] else SLOW_C if r[REQ_SLOW] else GREEN


def _flying(run, t: float, most: int) -> list[tuple]:
    """Requests that left in the last FLY seconds, at most `most`: the canary's first (it is only a few
    percent of the traffic, and the point of the picture)."""
    from live.worlds.canary_releases import REQ_CANARY, REQ_START

    rows = just_sent(run, "requests", t)
    canary = every([r for r in rows if r[REQ_CANARY]], most // 2)
    return canary + every([r for r in rows if not r[REQ_CANARY]], most - len(canary))


@adapts("canary_releases", "lanes")
class CanaryLanes(LaneAdapter):
    """Users wait for an answer (orange the longer they wait: a slow build shows here); requests fly to the
    door, the router: purple ones go to the new build. The door is dotted purple while the router splits the
    traffic, shut in red while many requests fail. The server is the fleet: its gauge is the new build's
    share (purple), or full blue when everyone is on the live build; its outline red while a build hurts
    requests. Under it: the live build, or the canary and its share."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.canary_releases import CANARY_C, LIVE_C, REQ_CANARY, REQ_END, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        waiting, _, outcomes = client_lanes(run, t, users, "requests", REQ_START, REQ_END, colour=_outcome,
                                            rare_first=True)
        flights = user_flights(_flying(run, t, FLIGHTS), t, REQ_START, lambda r: (
            slot(op_id(r[REQ_START]), users), CANARY_C if r[REQ_CANARY] else WHITE, bool(r[REQ_CANARY])))
        now = _now(w, run, t)
        s = int(t)
        asked, failed = run.series("ask", s - 1, s)[0], run.series("failed", s - 1, s)[0]
        hurting = sum(run.series("hurt", s - 2, s)) >= HURTING
        canary = now["new"] is not None
        return LaneFrame(
            users=waiting, flights=flights, outcomes=outcomes,
            closed=bool(asked) and failed / asked > CLOSED,
            door_color=CANARY_C if canary and not (asked and failed / asked > CLOSED) else None,
            fill=now["weight"] if canary else 1.0,
            gauge=CANARY_C if canary else RED if now["bad_live"] else LIVE_C,
            outline=RED if hurting else OUTLINE,
            state=_state(w, now),
        )


@adapts("canary_releases", "cluster")
class CanaryCluster(ClusterAdapter):
    """One node per instance (FLEET of them): the first ones run the new build while there is a canary
    (purple, as many as its share), the rest the live build (blue). A group turns red while its build fails
    requests, orange while it slows them. A sample of the requests flies from the users to the instance that
    got it (purple to the canary); failed ones die in red on the way."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.canary_releases import (
            CANARY_C,
            FAILED_C,
            LIVE_C,
            REQ_CANARY,
            REQ_END,
            REQ_HARMED,
            REQ_ID,
            REQ_OK,
            REQ_START,
            SLOW_C,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        now = _now(w, run, t)
        k = max(1, round(now["weight"] * FLEET)) if now["new"] is not None else 0

        def node(r) -> int:  # the instance a request went to
            return r[REQ_ID] % k if r[REQ_CANARY] and k else k + r[REQ_ID] % (FLEET - k)

        recent = run.rows("requests", t - 2.0, t + 1e-9)

        def colour(canary: bool, base: RGB) -> RGB:
            hurt = [r for r in recent if r[REQ_HARMED] and bool(r[REQ_CANARY]) == canary]
            if any(not r[REQ_OK] for r in hurt):
                return FAILED_C
            return SLOW_C if hurt else base

        nodes = [colour(True, CANARY_C)] * k + [colour(False, LIVE_C)] * (FLEET - k)
        flights = [(-1, node(r), (t - r[REQ_START]) / FLY, CANARY_C if r[REQ_CANARY] else WHITE)
                   for r in _flying(run, t, 2 * FLIGHTS)]
        failed = [r for r in just_ended(run, "requests", REQ_END, t) if not r[REQ_OK]]
        drops = [(-1, node(r), (t - r[REQ_END]) / BACK) for r in every(failed, OUTCOMES)]
        state, col = _state(w, now)
        if k:
            text = w.s("cluster_canary", state=state, live=now["live"], a=FLEET - k, b=k, n=FLEET)
        else:
            text = w.s("cluster_live", state=state, v=now["live"], n=FLEET)
        return ClusterFrame(nodes=nodes, flights=flights, drops=drops, state=(text, col))


@adapts("canary_releases", "relay")
class CanaryRelay(RelayAdapter):
    """The lanes picture with the router as a server of its own: users → the door → the router → the fleet
    (the old build and the new one). The router's gauge is the canary's share of the traffic, purple, with a
    purple outline, while a canary runs (empty when everyone is on the live build). Under it: the new build
    and its share, or "router". The fleet's gauge is the instances on the new build (purple) while there is
    a canary, full blue on the live build, full red while a bad build is live; its outline red while a build
    hurts requests. Under it: how many instances run the new build, or the live build. Requests fly user →
    door, then router → instance: purple to the new build, big and red when the bad build hurt them (failed
    or slowed them)."""

    def frame(self, variant: str, t: float, users: int) -> RelayFrame:
        from live.worlds.canary_releases import CANARY_C, LIVE_C, REQ_CANARY, REQ_HARMED, REQ_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return RelayFrame()
        lane = CanaryLanes(w).frame(variant, t, users)  # users, outcomes, the door and the outline
        rows = just_sent(run, "requests", t)
        shown = every([r for r in rows if r[REQ_HARMED]], FLIGHTS // 3)
        shown += every([r for r in rows if r[REQ_CANARY] and not r[REQ_HARMED]], FLIGHTS // 3)
        shown += every([r for r in rows if not r[REQ_CANARY] and not r[REQ_HARMED]], FLIGHTS - len(shown))
        flights, hops = [], []  # the first half of the way: user → door; the second: router → instance
        for r in shown:
            p = (t - r[REQ_START]) / FLY
            if p < 0.5:
                flights.append((slot(op_id(r[REQ_START]), users), 2 * p, WHITE, False))
            elif r[REQ_HARMED]:
                hops.append((2 * p - 1, RED, True))
            else:
                hops.append((2 * p - 1, CANARY_C if r[REQ_CANARY] else WHITE, bool(r[REQ_CANARY])))

        now = _now(w, run, t)
        if now["new"] is not None:
            k = max(1, round(now["weight"] * FLEET))
            relay = Relay(label=(w.s("relay_split", v=now["new"], w=now["weight"]), CANARY_C),
                          fill=now["weight"], gauge=CANARY_C, outline=CANARY_C)
            state = (w.s("relay_fleet", v=now["new"], b=k, n=FLEET), CANARY_C)
            fill, gauge = k / FLEET, CANARY_C
        else:
            relay = Relay(label=(w.s("relay_router"), OUTLINE), fill=0.0, gauge=LIVE_C, outline=OUTLINE)
            if now["bad_live"]:
                state, gauge = (w.s("relay_bad", v=now["live"]), RED), RED
            elif now["back"] is not None:
                state, gauge = (w.s("relay_back", v=now["back"]), GREEN), LIVE_C
            else:
                state, gauge = _state(w, now), LIVE_C
            fill = 1.0
        return RelayFrame(
            users=lane.users, flights=flights, outcomes=lane.outcomes, closed=lane.closed,
            fill=fill, gauge=gauge, outline=lane.outline, state=state, relay=relay, hops=hops,
        )

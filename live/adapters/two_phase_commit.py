"""The pictures for lab two_phase_commit: cluster (the coordinator and the three shards, and the
prepare / vote / commit messages between them) and lanes (the clients' view: transfers, the
coordinator as the door, the shards as the server)."""

from __future__ import annotations

from labs.two_phase_commit.scenario import (
    ABORTED, COMMITTED, M_ABORT, M_ACK, M_ANSWER, M_ASK, M_COMMIT, M_NO, M_PREPARE, M_TRANSFER, M_WRITE,
    M_YES, PARTIAL,
)
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA1, EXTRA2, GREEN, MUTED, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

MAX_FLIGHTS = 60  # messages drawn at once
RECENT = 2.0  # seconds a partial commit keeps its shards red
LOCKS_MAX = 24  # rows locked by prepared transfers that fill the shards' gauge
COLOURS = {M_TRANSFER: WHITE, M_WRITE: WHITE, M_PREPARE: WHITE, M_YES: BLUE, M_NO: MUTED, M_COMMIT: GREEN,
           M_ABORT: MUTED, M_ASK: EXTRA1, M_ANSWER: EXTRA1}


def _state(world, variant: str, t: float, partial: bool, st) -> tuple[str, tuple[int, int, int]]:
    """The words under the picture, and their colour."""
    from live.worlds.two_phase_commit import ST_CUT, ST_DOUBT, ST_DOWN

    inc = world.incident_at(variant, t)
    if partial:
        return world.s("state_partial"), RED
    if st is not None and st[ST_DOWN] & 1:
        return world.s("state_down"), RED
    if st is not None and st[ST_DOWN] & 0b1110:
        return world.s("state_shard_down"), RED
    if st is not None and st[ST_CUT]:
        return world.screen.STATES["partitioned"], RED
    if st is not None and sum(st[ST_DOUBT]):
        return world.s("state_doubt"), EXTRA2
    if inc is not None and inc.kind in ("refuse", "overload"):
        return world.s("state_no"), EXTRA2
    return world.screen.STATES["healthy"], GREEN


@adapts("two_phase_commit", "cluster")
class TwoPhaseCluster(ClusterAdapter):
    """The coordinator (n0, top left) and the shards n1, n2, n3. Transfers fly in from the clients
    (white); prepares fly to the shards (white), votes come back (blue yes, grey no), then the decision
    (green commit, grey abort); a shard in doubt asks the coordinator (light orange). A lost message
    stops half way and fades in red. A node is red while it is down; a shard turns orange while it holds
    transfers in doubt (prepared, no decision for over half a second: its rows stay locked), and red
    when it applied its part of a transfer that the other shards did not (a partial commit)."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.two_phase_commit import (
            MSG_ARRIVED, MSG_DEST, MSG_KIND, MSG_SENT, MSG_SRC, ST_CUT, ST_DOUBT, ST_DOWN, TX_APPLIED,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights, drops = [], []
        for m in every([m for m in run.rows("msgs", t - FLY, t + 1e-9) if m[MSG_KIND] != M_ACK], MAX_FLIGHTS):
            p = (t - m[MSG_SENT]) / FLY
            if m[MSG_ARRIVED] is None:  # lost: it never arrives
                if p < 0.5:
                    flights.append((m[MSG_SRC], m[MSG_DEST], p, COLOURS.get(m[MSG_KIND], WHITE)))
                else:
                    drops.append((m[MSG_SRC], m[MSG_DEST], (p - 0.5) * 2))
            else:
                flights.append((m[MSG_SRC], m[MSG_DEST], p, COLOURS.get(m[MSG_KIND], WHITE)))
        partials = w.recent_partials(run, t, RECENT)
        bad = 0  # shards holding a write of a partial commit
        for r in partials:
            bad |= sum(1 << i for i, at in enumerate(r[TX_APPLIED]) if 0 <= at <= t)
        st = w.state_at(variant, t)
        down = st[ST_DOWN] if st else 0
        nodes = [RED if down & 1 else BLUE]
        for i in range(3):
            if down >> (i + 1) & 1 or bad >> i & 1:
                nodes.append(RED)
            elif st is not None and st[ST_DOUBT][i]:
                nodes.append(EXTRA2)
            else:
                nodes.append(BLUE)
        groups = None
        if st is not None and st[ST_CUT]:
            groups = [1 if st[ST_CUT] >> i & 1 else 0 for i in range(4)]
        text, colour = _state(w, variant, t, bool(partials), st)
        return ClusterFrame(nodes=nodes, groups=groups, flights=flights, drops=drops,
                            state=(w.s("pic_state", state=text), colour))


@adapts("two_phase_commit", "lanes")
class TwoPhaseLanes(LaneAdapter):
    """Each transfer is a client; it flies to the coordinator (the door, closed in red while it is
    down) and waits for the answer: white, orange once its transfer is in doubt on a shard. It ends
    at the door green (committed everywhere), grey (aborted everywhere), orange (left in doubt) or red
    (committed on some shards only). The server is the three shards; its gauge is the rows locked by
    prepared transfers (orange while some are in doubt)."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.two_phase_commit import (
            ST_DOUBT, ST_DOWN, ST_HELD, TX_CEND, TX_ID, TX_PREP, TX_RESOLVED, TX_START, TX_STATUS,
        )
        from labs.two_phase_commit.scenario import DOUBT_AGE

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def in_doubt(r) -> bool:
            prepared = [p for p in r[TX_PREP] if p >= 0]
            return bool(prepared) and min(prepared) <= t - DOUBT_AGE and (
                r[TX_RESOLVED] is None or r[TX_RESOLVED] > t)

        found = {slot(r[TX_ID], users): (EXTRA2 if in_doubt(r) else WHITE, True)
                 for r in run.active("txns", t, TX_CEND)}
        flights = [(slot(r[TX_ID], users), (t - r[TX_START]) / FLY, WHITE, False)
                   for r in every(run.rows("txns", t - FLY, t + 1e-9), FLIGHTS)]
        span = run.max_dur.get("txns", 0.0)
        ended = [r for r in run.rows("txns", t - BACK - span, t + 1e-9) if t - BACK <= r[TX_CEND] <= t]
        bad = [r for r in ended if r[TX_STATUS] == PARTIAL]
        shown = every(bad, OUTCOMES)
        if len(shown) < OUTCOMES:
            shown += every([r for r in ended if r[TX_STATUS] != PARTIAL], OUTCOMES - len(shown))

        def colour(r):
            return {COMMITTED: GREEN, ABORTED: MUTED, PARTIAL: RED}.get(r[TX_STATUS], EXTRA2)

        outcomes = [(colour(r), (t - r[TX_CEND]) / BACK) for r in shown]
        partial = bool(w.recent_partials(run, t, RECENT))
        st = w.state_at(variant, t)
        down = bool(st and st[ST_DOWN] & 1)
        held = sum(st[ST_HELD]) if st else 0
        doubt = bool(st and sum(st[ST_DOUBT]))
        inc = w.incident_at(variant, t)
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes, closed=down, door_color=RED if down else None,
            fill=held / LOCKS_MAX, gauge=EXTRA2 if doubt else BLUE,
            outline=RED if partial else EXTRA2 if doubt or inc is not None else OUTLINE,
            state=_state(w, variant, t, partial, st),
        )

"""The pictures for lab deadlock_avoidance: lanes (transfers -> the service's workers as the door ->
the lock manager and ledger as the server) and cluster (accounts as nodes, the transfers waiting
between them as marching dots, a deadlock's cycle in red)."""

from __future__ import annotations

from labs.deadlock_avoidance.scenario import HOT, WORKERS
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, SLOW, every
from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, MUTED, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

OTHERS = 6  # slots in the bottom row for every other account (customers, small merchants)
EDGES = 24  # most waiting edges drawn at once


def _state(w, run, variant: str, t: float):
    """What the service is going through: (words, colour) and the latest sample."""
    from live.worlds.deadlock_avoidance import S_BUSY, S_CYCLES, S_WAITING

    sample = w.sample_at(run, t)
    inc = w.incident_at(variant, t)
    if sample is not None and sample[S_CYCLES]:
        state = (w.s("state_deadlock", n=sample[S_CYCLES]), RED)
    elif sample is not None and sample[S_BUSY] >= WORKERS:
        state = (w.s("state_frozen"), RED)
    elif sample is not None and sample[S_WAITING] >= 8:
        state = (w.s("state_waiting", n=sample[S_WAITING]), EXTRA2)
    elif inc is not None:
        state = (w.s(f"state_{inc.kind}"), EXTRA2)
    else:
        state = (w.screen.STATES["healthy"], GREEN)
    return state, sample


def _wait_colour(waited: float):
    return WHITE if waited < SLOW[0] / 5 else EXTRA1 if waited < SLOW[0] else EXTRA2 if waited < SLOW[2] else EXTRA3


@adapts("deadlock_avoidance", "lanes")
class DeadlockAvoidanceLanes(LaneAdapter):
    """Each transfer is a user, waiting (its colour: how long so far) for its answer. Dots fly to the
    service (the door): white a first try, orange a transfer that retried. At the door: green done,
    red failed or timed out. The door shuts (solid red) when every worker is stuck. The server is the
    lock manager and ledger: its gauge is the workers in use, red while a deadlock lasts."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.deadlock_avoidance import S_BUSY, S_CYCLES, T_END, T_ID, T_OK, T_START, T_TRIES, tries_colour

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        found = {slot(r[T_ID], users): (_wait_colour(t - r[T_START]), True) for r in run.active("transfers", t, T_END)}
        flying = run.rows("transfers", t - FLY, t + 1e-9)
        retried = [r for r in flying if r[T_TRIES] > 1]
        shown = every(retried, FLIGHTS // 2) + every([r for r in flying if r[T_TRIES] <= 1], FLIGHTS - min(len(retried), FLIGHTS // 2))
        flights = [(slot(r[T_ID], users), (t - r[T_START]) / FLY, tries_colour(r[T_TRIES]), r[T_TRIES] > 1)
                   for r in shown]
        span = run.max_dur.get("transfers", 0.0)
        ended = [r for r in run.rows("transfers", t - BACK - span, t + 1e-9) if t - BACK <= r[T_END] <= t]
        bad = every([r for r in ended if not r[T_OK]], OUTCOMES)
        back = bad + every([r for r in ended if r[T_OK]], OUTCOMES - len(bad))
        outcomes = [(GREEN if r[T_OK] else RED, (t - r[T_END]) / BACK) for r in back]

        state, sample = _state(w, run, variant, t)
        busy = sample[S_BUSY] if sample else 0
        stuck = busy >= WORKERS
        deadlock = bool(sample and sample[S_CYCLES])
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes,
            closed=stuck, door_color=RED if stuck else None,
            fill=busy / WORKERS, gauge=RED if deadlock or stuck else EXTRA2 if busy > WORKERS / 2 else BLUE,
            outline=OUTLINE, state=state,
        )


@adapts("deadlock_avoidance", "cluster")
class DeadlockAvoidanceCluster(ClusterAdapter):
    """The accounts: the six hot ones in the top row (escrow #1, fees #2, the big merchants #3-#6),
    and below them six slots that every other account shares (by its id), labelled with the account
    in it now. Clients sit on the left.

    An arrow of marching dots from account X to account Y is a transfer that holds X and waits for Y
    (from the clients when it holds nothing yet): white when it has just started waiting, orange the
    longer it waits. A deadlock is a cycle of such arrows: it is drawn in red, and its accounts turn
    red, until a timeout breaks it (or the server kills it). Money that moves flies from the payer to
    the payee in green. An account turns orange while transfers queue for it.
    """

    def node(self, account: int) -> int:
        if account in HOT:
            return HOT.index(account)
        return len(HOT) + account % OTHERS

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.deadlock_avoidance import (
            C_ACCOUNTS, T_DST, T_END, T_KIND, T_OK, T_SRC, W_HELD, W_T0, W_T1, W_WANT,
        )
        from labs.deadlock_avoidance.scenario import BATCH

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        n = len(HOT) + OTHERS
        names: dict[int, int] = {}  # bottom-row node -> the account shown in it
        waits = run.active("waits", t, W_T1)
        queue = [0] * n
        edges: dict[tuple[int, int], tuple[float, int]] = {}  # (from, to) -> (longest wait, an account)
        for x in waits:
            dst = self.node(x[W_WANT])
            src = -1 if x[W_HELD] < 0 else self.node(x[W_HELD])
            queue[dst] += 1
            for acc, k in ((x[W_WANT], dst), (x[W_HELD], src)):
                if k >= len(HOT):
                    names.setdefault(k, acc)
            if src == dst:
                continue
            waited = t - x[W_T0]
            if waited >= edges.get((src, dst), (-1.0, 0))[0]:
                edges[(src, dst)] = (waited, x[W_WANT])
        red_nodes: set[int] = set()
        red_edges: set[tuple[int, int]] = set()
        for c in w.cycles_at(run, t):
            ring = [self.node(a) for a in c[C_ACCOUNTS]]
            red_nodes.update(ring)
            for i, k in enumerate(ring):  # the holder of account i waits for account i + 1
                nxt = ring[(i + 1) % len(ring)]
                if k != nxt:
                    red_edges.add((k, nxt))
            for a in c[C_ACCOUNTS]:
                if self.node(a) >= len(HOT):
                    names[self.node(a)] = a
        flights = []
        march = (t * 1.2) % 1.0
        ranked = sorted(edges.items(), key=lambda e: -e[1][0])[:EDGES]
        for (src, dst), (waited, _) in ranked:
            colour = RED if (src, dst) in red_edges else _wait_colour(waited)
            for k in range(3):
                flights.append((src, dst, (march + k / 3) % 1.0, colour))
        for src, dst in red_edges - set(edges):
            for k in range(3):
                flights.append((src, dst, (march + k / 3) % 1.0, RED))
        span = run.max_dur.get("transfers", 0.0)
        moved = [r for r in run.rows("transfers", t - FLY - span, t + 1e-9)
                 if r[T_OK] and t - FLY <= r[T_END] <= t and r[T_KIND] != BATCH]
        for r in every(moved, 20):
            a, b = self.node(r[T_SRC]), self.node(r[T_DST])
            if a != b:
                flights.append((a, b, (t - r[T_END]) / FLY, GREEN))
                for acc, k in ((r[T_SRC], a), (r[T_DST], b)):
                    if k >= len(HOT):
                        names.setdefault(k, acc)

        nodes = []
        for k in range(n):
            if k in red_nodes:
                nodes.append(RED)
            elif queue[k] >= 3:
                nodes.append(EXTRA2)
            elif queue[k]:
                nodes.append(EXTRA1)
            else:
                nodes.append(BLUE if k < len(HOT) or k in names else MUTED)
        labels = [(f"#{a}", MUTED) for a in HOT] + [(f"#{names[k]}" if k in names else "", MUTED)
                                                     for k in range(len(HOT), n)]
        for k in red_nodes:
            labels[k] = (labels[k][0], RED)
        state, _ = _state(w, run, variant, t)
        return ClusterFrame(nodes=nodes, flights=flights, columns=len(HOT), labels=labels,
                            state=(w.s("pic_state", n=len(waits), state=state[0]), state[1]))

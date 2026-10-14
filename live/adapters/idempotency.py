"""The lanes picture for lab idempotency: clients, the payment service (the door), the ledger (the server)."""

from __future__ import annotations

from labs.idempotency.scenario import CONFLICT, OK
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BLUE, EXTRA, EXTRA2, GREEN, MUTED, RED
from live.views.base import adapts
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot

LEDGER_MAX = 60.0  # charges running at once that fill the ledger's gauge


@adapts("idempotency", "lanes")
class IdempotencyLanes(LaneAdapter):
    """Each payment is a user; its tries fly to the payment service; charges fill the ledger's gauge.
    A try that charged a second time comes back red."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from live.worlds.idempotency import (
            PAY_END, PAY_ID, TRY_CHARGED, TRY_DUP, TRY_END, TRY_N, TRY_OUTCOME, TRY_PAY, TRY_START,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()
        span = run.max_dur.get("attempts", 0.0) + 0.1
        tries: dict[int, int] = {}
        doubled: set[int] = set()
        for r in run.rows("attempts", t - span - 5, t + 1e-9):
            tries[r[TRY_PAY]] = max(tries.get(r[TRY_PAY], 0), r[TRY_N])
            if r[TRY_DUP] and r[TRY_END] <= t:
                doubled.add(r[TRY_PAY])
        found = {}
        for p in run.active("payments", t, PAY_END):
            pid = p[PAY_ID]
            colour = RED if pid in doubled else EXTRA[min(3, tries.get(pid, 0))]
            found[slot(pid, users)] = (colour, True)

        flying = run.rows("attempts", t - FLY, t + 1e-9)
        flights = [(slot(r[TRY_PAY], users), (t - r[TRY_START]) / FLY, EXTRA[min(3, r[TRY_N])], r[TRY_N] > 0)
                   for r in every(flying, FLIGHTS)]
        ended = [r for r in run.rows("attempts", t - BACK - span, t + 1e-9) if t - BACK <= r[TRY_END] <= t]

        def colour(r: tuple):
            if r[TRY_DUP]:
                return RED
            return GREEN if r[TRY_OUTCOME] == OK else EXTRA2 if r[TRY_OUTCOME] == CONFLICT else MUTED

        outcomes = [(colour(r), (t - r[TRY_END]) / BACK) for r in every(ended, OUTCOMES)]
        charging = sum(1 for r in run.active("attempts", t, TRY_END) if r[TRY_CHARGED])

        inc = w.incident_at(variant, t)
        words = w.screen.STATES
        if inc is not None and inc.kind == "slow":
            state, gauge, outline = (w.s("state_slow"), EXTRA2), EXTRA2, EXTRA2
        elif inc is not None and inc.kind == "resets":
            state, gauge, outline = (words["degraded"], EXTRA2), BLUE, EXTRA2
        elif inc is not None:
            state, gauge, outline = (words["busy"], EXTRA2), EXTRA2, OUTLINE
        else:
            state, gauge, outline = (words["healthy"], GREEN), BLUE, OUTLINE
        return LaneFrame(
            users=found, flights=flights, outcomes=outcomes,
            door_color=EXTRA2 if inc is not None and inc.kind == "resets" else None,  # answers lost here
            fill=charging / LEDGER_MAX, gauge=gauge, outline=outline, state=state,
        )

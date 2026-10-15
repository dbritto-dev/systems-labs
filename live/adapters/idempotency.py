"""The pictures for lab idempotency: lanes (clients, the payment service as the door, the ledger as
the server), cluster (clients -> the payment service, which asks the key store or charges the ledger)
and relay (clients -> the payments API, where the key store replays answers -> the ledger)."""

from __future__ import annotations

from labs.idempotency.scenario import CONFLICT, LOST, OK
from live.adapters.common import BACK, FLIGHTS, FLY, OUTCOMES, every
from live.canvas import BG, BLUE, EXTRA, EXTRA2, GREEN, MUTED, RED, WHITE, mix
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame, slot
from live.views.lanes_relay import Relay, RelayAdapter, RelayFrame

LEDGER_MAX = 60.0  # charges running at once that fill the ledger's gauge
API_MAX = 150.0  # tries in progress in the payments API that fill its gauge (relay picture)


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


@adapts("idempotency", "cluster")
class IdempotencyCluster(ClusterAdapter):
    """The topology: clients -> the payment service (node 0), which either answers from the key store
    (node 1, right) or charges the ledger (node 2, below).

    Tries fly in coloured by their number (white first try, deeper orange for each retry). Past the
    service, a charge flies to the ledger: white the first time, red when it charges a payment a
    second time. A try answered without charging (a replayed receipt) flies to the key store in
    green; a 409 bounces back to the clients in orange. Charges still running sit at the ledger, so
    a slow ledger piles them up. Answers lost on the way back stop half way and fade (grey).
    """

    SERVICE, STORE, LEDGER = 0, 1, 2

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from live.worlds.idempotency import TRY_CHARGED, TRY_DUP, TRY_END, TRY_N, TRY_OUTCOME, TRY_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights = []
        for r in every(run.rows("attempts", t - FLY, t + 1e-9), FLIGHTS):
            p = (t - r[TRY_START]) / FLY
            if p < 0.5:  # into the service
                flights.append((-1, self.SERVICE, p * 2, EXTRA[min(3, r[TRY_N])]))
            elif r[TRY_CHARGED]:  # charged: on to the ledger
                flights.append((self.SERVICE, self.LEDGER, (p - 0.5) * 2, RED if r[TRY_DUP] else WHITE))
            elif r[TRY_OUTCOME] == CONFLICT:  # 409: back to the client, which tries later
                flights.append((self.SERVICE, -1, (p - 0.5) * 2, EXTRA2))
            else:  # answered without charging: the receipt comes from the key store
                flights.append((self.SERVICE, self.STORE, (p - 0.5) * 2, GREEN))
        # Charges still running crawl to the ledger (a slow ledger piles them up on the way).
        charging = [r for r in run.active("attempts", t, TRY_END)
                    if r[TRY_CHARGED] and t - r[TRY_START] >= FLY]
        flights += [(self.SERVICE, self.LEDGER, 0.3 + 0.65 * (t - r[TRY_START]) / (r[TRY_END] - r[TRY_START]),
                     RED if r[TRY_DUP] else WHITE) for r in every(charging, FLIGHTS)]
        # Answers lost on the way back: half way to the clients, fading.
        span = run.max_dur.get("attempts", 0.0)
        lost = [r for r in run.rows("attempts", t - BACK - span, t + 1e-9)
                if t - BACK <= r[TRY_END] <= t and r[TRY_OUTCOME] == LOST]
        flights += [(self.SERVICE, -1, 0.5, mix(MUTED, BG, (t - r[TRY_END]) / BACK))
                    for r in every(lost, OUTCOMES)]

        doubled = any(r[TRY_DUP] for r in run.rows("attempts", t - 1 - span, t + 1e-9)
                      if t - 1 <= r[TRY_END] <= t)
        inc = w.incident_at(variant, t)
        words = w.screen.STATES
        if doubled:  # a payment was just charged a second time
            ledger, state = RED, (w.s("state_double"), RED)
        elif inc is not None and inc.kind == "slow":
            ledger, state = EXTRA2, (w.s("state_slow"), EXTRA2)
        elif inc is not None and inc.kind == "resets":
            ledger, state = BLUE, (words["degraded"], EXTRA2)
        else:
            ledger, state = BLUE, (words["healthy"], GREEN)
        service = EXTRA2 if inc is not None and inc.kind == "resets" else BLUE
        return ClusterFrame(nodes=[service, BLUE, ledger], flights=flights,
                            state=(w.s("pic_state", state=state[0]), state[1]))


@adapts("idempotency", "relay")
class IdempotencyRelay(RelayAdapter):
    """Clients → the door → the payments API (the relay: your PaymentService with its key store) → the
    payment provider's ledger (the server on the right, as in lanes).

    The API's gauge is the tries in progress in it (against API_MAX), orange past 80% and red when full;
    retries pile up there while the ledger is slow. A retry the key store answers with the saved receipt
    never reaches the provider: it stops at the API's edge, green, and the word under the API counts them
    (replayed in the last second); a 409 (the same key still in progress) stops there too, orange. Charges
    fly on to the provider, crawling while it is slow: white the first time, red and bigger when a payment
    is charged a second time, which also turns the provider red (CHARGED TWICE)."""

    def frame(self, variant: str, t: float, users: int) -> RelayFrame:
        from live.worlds.idempotency import TRY_CHARGED, TRY_DUP, TRY_END, TRY_OUTCOME, TRY_START

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return RelayFrame()
        lane = IdempotencyLanes(w).frame(variant, t, users)  # the clients, their tries, the ledger
        span = run.max_dur.get("attempts", 0.0)
        recent = run.rows("attempts", t - span - FLY - 1e-9, t + 1e-9)
        charges = [r for r in recent if r[TRY_CHARGED] and t <= r[TRY_START] + max(FLY, r[TRY_END] - r[TRY_START])]
        shown = every([r for r in charges if r[TRY_DUP]], FLIGHTS // 2)
        shown += every([r for r in charges if not r[TRY_DUP]], FLIGHTS - len(shown))
        hops = [(min(0.95, (t - r[TRY_START]) / max(FLY, r[TRY_END] - r[TRY_START])), RED if r[TRY_DUP] else WHITE,
                 bool(r[TRY_DUP])) for r in shown]
        ended = [r for r in recent if t - BACK <= r[TRY_END] <= t and not r[TRY_CHARGED]]
        replays = [r for r in ended if r[TRY_OUTCOME] != CONFLICT]
        conflicts = [r for r in ended if r[TRY_OUTCOME] == CONFLICT]
        hops += [(0.04 * j, GREEN, False) for j in range(min(3, (len(replays) + 1) // 2))]
        hops += [(0.12 + 0.04 * j, EXTRA2, False) for j in range(min(2, (len(conflicts) + 1) // 2))]

        replayed = sum(1 for r in run.rows("attempts", t - 1 - span, t + 1e-9)
                       if t - 1 <= r[TRY_END] <= t and not r[TRY_CHARGED] and r[TRY_OUTCOME] != CONFLICT)
        busy = len(run.active("attempts", t, TRY_END)) / API_MAX
        gauge = RED if busy >= 1 else EXTRA2 if busy >= 0.8 else BLUE
        label = (w.s("relay_replayed", n=replayed), GREEN) if replayed else (w.s("relay_api"), WHITE)
        relay = Relay(label=label, fill=busy, gauge=gauge, outline=OUTLINE if gauge == BLUE else gauge)
        doubled = any(r[TRY_DUP] for r in run.rows("attempts", t - 1 - span, t + 1e-9) if t - 1 <= r[TRY_END] <= t)
        state = (w.s("state_double"), RED) if doubled else lane.state
        return RelayFrame(users=lane.users, flights=lane.flights, outcomes=lane.outcomes, door_color=lane.door_color,
                          fill=lane.fill, gauge=lane.gauge, outline=RED if doubled else lane.outline, state=state,
                          relay=relay, hops=hops)

# Lab: sagas

*[Leer en español](es/README.md)*

Customers place ~20 orders a second. Each order spans three services and there is no transaction
across them, so your `Orchestrator` runs it as a saga: charge the card (payments), reserve the
items (stock), book a courier (shipping). About 2% of cards are declined, always. At random times,
like in production, a flash sale sells items out (the reservation says no after the card was
charged), the carrier is down (the booking says no after both), a service times out (the step may
or may not have happened: the answer was lost), or the orchestrator itself dies mid-saga (a deploy,
an OOM kill). A new orchestrator starts a few seconds later with the same services and the same
log, `recover()` is called once, and orders that arrived meanwhile wait at the door. The run never
restarts. The first incident is always a slow carrier at 0:20–0:30 whose waiting sagas get the
orchestrator OOM-killed at 0:26 (back at 0:28).

```
uv run python -m live saga_orchestration          # watch it; edit main.py and save
uv run python -m live saga_orchestration --lesson # the concept, links and a checklist
uv run pytest labs/saga_orchestration             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 No rollback (given) | charge, reserve, book; a failure just stops | charged customers with no order, items held for nobody (red); rolled back 4%, 54 half done |
| 1 Compensations | on `StepFailed`, `compensate`: undo the steps whose refs came back, last first | definite failures roll back cleanly (orange), but a booking that timed out and still happened, and every saga the OOM kill cut short, stay half done |
| 2 Resumable sagas | `key=saga_id` on every call, `attempt` retries timeouts, the log says "running" / "compensating", `recover()` resumes every unfinished saga | nothing half done, no double charge, every order that could complete does; every goal OK |

Goals, judged per incident (sagas started from 2 s before it, since they are still running when
it starts): baseline ok (before), rolled back 100% (sagas you gave up on hold nothing you were told
happened; "none" when none gave up), half done = 0 (money taken, items held or a courier booked for
an order that is not complete), double charges = 0, completed ≥ 95% of the orders nobody said no to,
and p99 time to finish < 1 s for sagas started in the 5 s after.

- **Why a timeout is not a failure.** Half the timeouts lose the answer, not the request: the
  courier is booked and you never got its ref. Undo it by key (undoing what never happened does
  nothing), or retry with the same key and get the first ref back.
- **Why keys.** A retry without a key after a lost answer charges the card again. Resuming after a
  crash re-runs steps that may have happened: only keys make that safe.
- **Why "compensating" in the log.** A saga that crashes while undoing must keep undoing. If the log
  still says "running", the new orchestrator goes forward, and the replayed (already refunded)
  charge lets the order ship unpaid.

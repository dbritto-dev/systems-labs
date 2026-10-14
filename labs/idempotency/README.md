# Lab: idempotency keys

*[Leer en español](es/README.md)*

Clients pay ~40 times a second through your `PaymentService.charge(key, account, amount)`.
Every payment carries an idempotency key. A client waits up to 1 s for an answer; if none
comes it retries with the same key (up to 4 tries, backing off), and after a 409 (`Conflict`)
it retries a little later. At random times, like in production, the ledger gets slow (a lock,
disk I/O, a failover: the retry arrives while the first try is still charging), answers get
lost on the way back (a load balancer reset, a deploy draining connections: the card was
charged, the client never heard), or clients send the same payment twice at once (an SDK bug,
a double click). The run never restarts. The first incident is always a slow ledger at
0:20–0:30.

```
uv run python -m live idempotency          # watch it; edit main.py and save
uv run python -m live idempotency --lesson # the concept, links and a checklist
uv run pytest labs/idempotency             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 No idempotency (given) | every try charges | every retried payment is charged twice (red); replayed 0% |
| 1 Replays answers | `get` the key; if there is a receipt return it, else charge and `set` it | retries after a lost answer are replayed (100%), but a retry that comes while the first try is still charging, or two tries at once, still charge twice |
| 2 Reserved keys | claim the key with `store.add(key, IN_PROGRESS, ttl)` before charging; duplicates wait for the receipt (or raise `Conflict`); everything expires | no double charge, every try gets the same receipt; every goal OK |

Goals, judged per incident: baseline ok (before), replayed ≥ 95% of the retries that come after
the first charge (during and 5 s after; "none" when no retry came that late, and passes),
double charges = 0 (during), same receipt for every try of a payment (during), p99 < 500 ms for
payments started in the 5 s after.

- **Why `get` then `set` is not enough.** They are two steps, ~1 ms apart, with a 20 ms to 2 s
  charge in between. A second try that arrives in that gap finds nothing and charges again.
  `add` (Redis `SET NX`, or `INSERT ... ON CONFLICT DO NOTHING`) checks and writes in one step.
- **Why the p99 goal.** One global lock around `charge` also never charges twice, but then one
  slow charge holds up every other payment: after a slow ledger the queue takes long to drain.
  Lock per key, not per service.

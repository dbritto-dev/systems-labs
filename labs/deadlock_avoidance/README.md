# Lab: deadlock avoidance

*[Leer en español](es/README.md)*

Customers pay merchants ~200 times a second through one payments service, which runs at most 64
transfers at once (its database connections); the rest wait at the door, and a client gives up
after 2 s. Every transfer, in your `Payments`, locks both accounts (row locks in the ledger, see
`api.py`), moves the money, writes the audit log (2–6 ms a row) and releases the locks. A few
accounts are hot: the marketplace's escrow (#1) and fee (#2) accounts and four big merchants
(#3–#6, a Zipf share of all payments). Like MySQL with `innodb_deadlock_detect = OFF`, nobody breaks
a deadlock for you: the server kills a transaction after 8 s. At random times, like in production,
a payout run moves money among the hot accounts in both directions (and fills the audit log), a
merchant refunds the buyers who keep paying it (transfers against the usual direction), the audit
log stalls now and then (0.4–0.8% of writes take 0.2–0.6 s), or a batch job (a fee sweep) locks
10–25 accounts at once. The run never restarts. The first incident is always a payout run at
0:20–0:30.

```
uv run python -m live deadlock_avoidance          # watch it; edit main.py and save
uv run python -m live deadlock_avoidance --lesson # the concept, links and a checklist
uv run pytest labs/deadlock_avoidance             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see in the first payout run |
|---|---|---|
| 0 Request order (given) | `lock_all` acquires `src`, then `dst`, waiting forever | 1–2 deadlocks within a second, then every worker is stuck: the door shuts, 14–22% of transfers complete, p99 2 s (the client's timeout) |
| 1 Timeouts and retry | `lock_all`: `timeout=0.05`; on `LockTimeout` `release_all()`, sleep `backoff(attempt, rng)`, retry up to 8 tries | no deadlock lasts (cycles break in 50 ms), but timeouts fire on long waits at the hot accounts too: 1.4–1.6 retries per transfer, 88–91% complete, p99 1.8–2 s |
| 2 One lock order | `lock_order` = `sorted(set(accounts))` in `transfer` and `settle`; audit after releasing; `LOCK_TIMEOUT = 2`, 3 tries as a safety net | no cycle ever forms: 100% complete, p99 ~23 ms, 0 retries; every goal OK |

Goals, judged per incident, for transfers started during it: deadlocks = 0 (a cycle of waiting
transfers that lasts 1 s), completed ≥ 99%, p99 ≤ 100 ms (users' transfers, not batches), retries ≤
0.1 per transfer, and lost updates = $0 (money that appeared or disappeared because a commit wrote
over another one's, during the incident and 5 s after).

Two pictures: `lanes` (opens first) shows the transfers as users (their colour: how long they have
waited), flying to the service (the door: white a first try, orange a retry) and what came back:
green done, red failed or timed out. The door shuts when every worker is stuck; the server is the
lock manager and ledger, its gauge the workers in use. `cluster` shows the accounts: the six hot
ones on top (#1–#6), and six slots below shared by every other account. A transfer that holds X and
waits for Y is an arrow of marching dots from X to Y (white, then orange as it waits); a deadlock is
a cycle of arrows, in red; money that moves flies from payer to payee in green. Press `v` to switch.

- **Why timeouts are not enough.** A timeout cannot tell a deadlock from a long wait at a busy
  account: under contention it fires on both, throws the work away, and the retries add load
  (`TIMEOUTS`). Without jitter, transfers that collided retry together (`NO_JITTER`); giving up at
  once fails 4–5% of transfers (`GIVE_UP`).
- **Why one order works.** A cycle needs a transfer that holds a bigger id and waits for a smaller
  one. Sorted locking never does that, for two accounts or for a batch of 25.
- **Why the critical section must be short.** Order alone stops deadlocks, not waiting: with the
  audit write inside the locks, the big merchants' queues grow (p99 1.4–2 s, `ORDER_ONLY`), and with
  short timeouts on top every long wait becomes a retry (`ORDER_SLOW_TIMEOUT`).
- **Why both locks.** Lock only the payer and nothing ever waits in a circle, but two payments to
  the same merchant read its balance, and the second commit writes over the first: ~$36,000 appears
  or disappears in ten seconds (`PAYER_ONLY`).

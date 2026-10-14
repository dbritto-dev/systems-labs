# Lab: optimistic locking

*[Leer en español](es/README.md)*

Users buy ~50 times a second through three app servers, each with its own
`StockService.adjust(item, delta)` over one shared stock table. Each request is a
read-modify-write: read the row, add `delta` (a sale takes 1–3 units), write the new value
back. A user waits up to 1 s; a 409 (`Conflict`) is an error page. At random times, like in
production, a flash sale sends most of 2–3.5x the traffic to one item (a push notification, a
pricing mistake), a bulk import restocks the popular items while users buy them (a supplier feed,
a nightly sync), or the network to the database gets slow (a zone failover, packet loss: the gap
between a request's read and its write widens). The run never restarts. The first incident is
always a flash sale at 0:20–0:30.

```
uv run python -m live optimistic_locking          # watch it; edit main.py and save
uv run python -m live optimistic_locking --lesson # the concept, links and a checklist
uv run pytest labs/optimistic_locking             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Last write wins (given) | `read`, add `delta`, `write` | every request served in ~6 ms, and the flash sale loses ~250 updates (red): the stock is wrong and nobody knows |
| 1 Version check | `compare_and_set(item, new, row.version)`; raise `Conflict` when it matches no row | nothing is lost, but ~13% of the requests in a flash sale get a 409 (orange) |
| 2 Retry and merge | on a conflict, wait `backoff(attempt, rng)` (full jitter, capped), read again, re-apply `delta`, up to `MAX_TRIES` | nothing lost, 409s ~0%, p99 ~50 ms in a flash sale (~250 ms when the database is slow); every goal OK |

Goals, judged per incident: baseline ok (requests served before), lost updates = 0, 409s ≤ 1%,
p99 < 500 ms and served ≥ 98% (all for the requests started during the incident).

Two pictures: `lanes` (opens first) shows users sending writes (white, deeper orange for each
retry) to the API, and what came back at the door: served green, 409 orange, an update that erased
others red. `cluster` shows the three app servers and the database: writes that commit white,
writes that lose the version check orange, writes that erase others red; press `v` to switch.

- **Why a lock in your code is not enough.** An `asyncio.Lock` per item works inside one app
  server; the other two have their own, and still write over each other. The check has to happen
  in the database, in the same statement as the write.
- **Why re-read.** Retrying the same `compare_and_set` with the version you read first can never
  win again: the row has moved on. Read again and apply your change to what is there now.
- **Why jitter and a cap.** The requests that lost a race lost it together; without jitter they
  come back together and collide again. Without a cap, a few unlucky requests wait seconds
  (`0.1 * 2 ** attempt` fails the p99 goal).

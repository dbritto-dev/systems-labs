# Lab: connection pool

Users send ~100 requests/s (drifting slowly). Each request asks your `Pool` for a
database connection, runs one query, and gives the connection back. Opening a
connection costs ~40 ms (TLS, auth, a new backend process); a query ~8 ms. The
database allows at most **50** open connections ("too many connections" beyond) and
slows down once more than ~20 work at once.

At random times, like in production, the database **slows down** (autovacuum, a long
report holding locks, a backup saturating the disks, a dropped index) or **traffic
spikes** 5-7x (a marketing email, a cron job fanning out). The first incident is always
a slowdown at 0:20-0:32. The run never restarts: the pool and its connections carry on.

```
uv run python -m live conn_pool            # watch it; edit main.py and save
uv run python -m live conn_pool --lesson   # the concept, links and a checklist
uv run pytest labs/conn_pool               # x = not yet, X = done
```

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 New connection (given) | open and close a connection per request | reuse 0%; a slowdown or a spike hits 50 connections and requests are refused |
| 1 Pool | keep released connections and hand them out again | reuse ~100%; a slowdown still grows the pool to 50: refused requests |
| 2 Bounded pool | never open more than `max_size` (20); wait for a release | no refusals, but during a slowdown requests wait 2-7 s |
| 3 Bounded pool + timeout | give up after `timeout` (0.5 s): raise `PoolTimeout` | waits stay at 0.5 s; some requests fail fast while it is slow |

Goals, judged per incident: baseline ok (before), reuse ≥ 90% of served requests (before),
no "too many connections" errors (during), p99 wait for a connection < 1 s (during),
≥ 95% of requests started in the 5 s after served within 1 s (after).

A request still waiting when an incident is judged counts with the time it has waited so
far. A bigger pool does not make a slow database faster: past ~20 connections working
at once, every query just takes longer.

# Lab: deadline propagation

*[Leer en español](es/README.md)*

A request goes through a chain of four services: gateway → api → orders → db. Users send
~40 requests/s and give up after 2 s. Every service runs your `handle`: its own work (a
few ms; the db's query) while holding one of its workers, then a call to the next service,
holding the worker while it waits. A call is a network request: when the caller stops
waiting, the callee does not know and carries on.

At random times, like in production, the db gets slow: 120–160 ms a query instead of 15
(a slow query plan, lock contention, a degraded replica, a GC storm, a maintenance job, a
cold cache after a failover). With 3 connections it then answers ~20 queries/s, half of what
users ask, and a queue forms in front of it. The first incident is always at 0:20–0:30,
150 ms a query.

```
uv run python -m live deadline_propagation            # watch it; edit main.py and save
uv run python -m live deadline_propagation --lesson   # the concept, links and a checklist
uv run pytest labs/deadline_propagation               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see (first incident, 12 seeds) |
|---|---|---|
| 0 Per-hop timeouts (given) | each hop waits its own `HOP_TIMEOUT` (2 s) from its own call | callers keep waiting after the user left (overrun p99 25 ms–1.5 s); 31–51% of the work is for users who left; served 28–58% of what the db could do |
| 1 Deadline passed down | send `next_deadline(deadline)` (yours minus `MARGIN`), wait until your own deadline | overrun 0, but the db still runs queued queries for users who left (wasted 38–57%), so served stays at 20–47% |
| 2 Deadline + skip late work | `if expired(...)`: raise `DeadlineExceeded` before the work and before the next call | no wasted work; the queue drains at once and the db serves 97–100% of what it can |

Goals, judged per slowdown: baseline ok (served ≥ 99%, before); wasted ≤ 5% (the share of
the services' own work done after its user had left, for requests that reach a service from
the start of the slowdown until 3 s after it; during); served ≥ 80% of the most possible
(requests served vs what the slow db could answer, or what users asked if less; during);
overrun p99 < 10 ms (how long a caller kept waiting on a call after its user had left;
during).

**Lanes picture** (the default). Users on the left wait at the gateway door: white, orange
after 1 s. A user who gave up while the chain still works on their request becomes a red
ring. The server box is the chain; its gauge is the db's busy connections, red while they
run queries for users who left. The bars show where requests are right now in each
service: working (white), queued (orange), for users who left (red). The chart shows db
queries a second: white for users still waiting, red for users who had already left.

**Cluster picture.** Press `v` (or `--view cluster`) to see the chain as four nodes
(gateway, api top; orders, db bottom, read like a Z). Requests fly in from the clients;
calls fly from each service to the next and wait near the callee. A call whose user has
already left is red: work and waiting for nobody. Calls cut by a timeout or that fail die
in red on their edge; a node turns red while most of its work is for users who left.

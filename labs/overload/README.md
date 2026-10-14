# Lab: overload & queues

*[Leer en español](es/README.md)*

A server works through a queue at 100 requests/s (10 ms each). Users send ~75
requests/s (drifting slowly). A user waits 1 s for a reply, then gives up on that
try and sends it again (at most 2 retries); the try they gave up on stays in the
queue. A rejection is an answer: no retry.

Incidents come at random, like in production: **traffic spikes** (2–3x for 5–15 s:
a viral post, a thundering herd after a deploy…) and **capacity drops** (the server
runs at 30–50%: a node lost, a noisy neighbour…). The first incident is always a
2.5x spike at 0:20–0:30. The run never restarts, so a broken queue stays broken.

```
uv run python -m live overload            # watch it; edit main.py and save
uv run python -m live overload --lesson   # the concept, links and a checklist
uv run pytest labs/overload               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` (`Policy`) | What you see |
|---|---|---|
| 0 Unbounded FIFO (given) | admit everything, oldest first | the queue grows to thousands; the server works for users who left (WASTING); it never recovers, even after the spike |
| 1 Bounded queue | `admit`: reject when the queue holds `MAX_QUEUE` | the door rejects, the queue stays at 200, but the work is still for users who left |
| 2 Skip late requests | `drop`: `too_late(request, now)` (less than 0.1 s left) | no wasted work, goodput back, recovers in seconds, but replies take ~0.9 s |
| 3 Adaptive LIFO | `newest_first`: `overloaded(queue_len)` (queue > 20) | replies in ~20 ms even at 2.5x the traffic |

Goals, judged per incident: baseline ok (before); the queue stays ≤ 250 (during);
waste < 5% of the work (during and 5 s after); goodput ≥ 80% of what was possible
(the server's capacity, or what users asked if less) (during); median reply < 300 ms
(during); recovered within 5 s (after: 3 s in a row with ≥ 90% of first tries
answered in time).

Why skipping uses a margin: a request taken from the head of a full FIFO queue is
almost exactly as old as the timeout, so a reply would land just after the user gave
up. `too_late` skips it when less than `MARGIN` (0.1 s) is left: the deadline travels
with the request, as with gRPC deadlines.

**Second picture.** Press `v` (or `--view cluster`) to see the topology: clients → queue → server. The queue turns orange as it fills (deeper when most of it is for users who left); rejected tries die in red on the way in.

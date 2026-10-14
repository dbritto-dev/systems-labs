# Lab: event loop blocking

*[Leer en español](es/README.md)*

An asyncio web service handles ~100 requests/s on **one event loop**. 82% of the requests are light
(parse, an async DB query, render: ~10 ms). The rest make one **blocking call** each: a sync DB
driver (8%, ~10 ms), a sync HTTP client to a partner API (4%, ~30 ms), an image **resize** on upload
(4%, ~40 ms of CPU) or a report export's big **json.dumps** (2%, ~30 ms of CPU). Every handler runs its
blocking call through your `Service.run_blocking(call)`, which today just calls `call()` on the loop's
thread: for those milliseconds **nothing else runs**, not another request, not a timer, not the
health check. A user gives up after 5 s (a 504; the handler goes on regardless). The load balancer
checks `/health` every 2 s with a 1 s timeout; after **3 failures in a row the orchestrator kills
the process**, and a new one takes 10 s to start (503s meanwhile, and everything it held is lost).

At random times, like in production: an **upload batch** makes resizing slow (a wedding photographer,
a catalogue import, a camera-roll sync: 4.6-6 cores of resizing), a **sync dependency gets slow** (a
lock in the database, a degraded partner API, a slow DNS resolver: sync calls 30-80x slower), a
**burst of report exports** (month end, a dashboard refreshing in every tab: 4.5-6 cores of
json.dumps) or **garbage-collection pauses** stop the process 18-36 ms, again and again (a cache
refill, a leak, a CPU quota). The first incident is always an **upload batch at 0:20-0:50**. The run
never restarts.

The machine has 4 cores. In this lab threads are simulated, with a **GIL**: a thread waiting on I/O
releases it, but CPU work in threads runs one call at a time, and the loop itself runs 2x slower
while a thread computes. Processes have their own GIL; sending a call to one costs 1 ms of pickling
on the loop. See `api.py`.

```
uv run python -m live event_loop_blocking            # watch it; edit main.py and save
uv run python -m live event_loop_blocking --lesson   # the concept, links and a checklist
uv run pytest labs/event_loop_blocking               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see (the first upload batch) |
|---|---|---|
| 0 Sync calls on the loop (given) | `run_blocking` calls `call()` | already before it: loop lag p99 60-90 ms, light requests p99 135-180 ms. During it each resize holds the loop ~400 ms: lag p99 1-4 s, 13-14 health checks fail, the process is killed (twice), 6-9% of the heavy requests served |
| 1 Offloaded to threads | `await to_thread(call)` | the loop stays free (lag ~1 ms, no failed check, light p99 12 ms), but 8 threads share one GIL: 565-684 calls queue up, 3-4% of the heavy requests served in time, and the queue takes minutes to drain afterwards |
| 2 Bounded executors | CPU to a `ProcessPool(4)`, I/O to a `ThreadPool(16)`, each queue bounded (8 and 32: `Overloaded` → 503), and a lag watchdog | lag <1 ms, light p99 11 ms, 86-91% of the heavy requests served (the rest get a 503 at once), at most 8 queued, lag reported every second |

Goals, judged per incident (during it): loop lag p99 < 50 ms (measured from outside your code, every
50 ms), health-check failures = 0, light requests p99 < 100 ms (a failed one counts as 5 s), heavy
requests served in time ≥ 70%, calls queued in the executors ≤ 50, and your watchdog's lag reports
in ≥ 90% of the seconds. The stage is judged from the first upload batch: a stalled loop (lag or
health checks) is stage 0; a free loop that misses another goal is stage 1.

Why each part of stage 2 matters (the first upload batch): with the right pools but no queue limit
the CPU queue grows to 67-121 calls and only 61-85% of the heavy requests are served in time; with
bounded queues but CPU work on threads (one pool for everything) the GIL serves only 45-50%; without
the watchdog nobody sees the lag (0% reported). The other incidents teach the rest: a slow dependency
fills the I/O pool, not the CPU one (bulkheads); GC pauses are lag no offloading removes, and only the
watchdog shows it (10-26 ms p99 with the reference).

**The pictures.** The window opens on the lanes: users → the process's socket (the door: shut red
while the process is killed and restarting) → the event loop as the server, its gauge how much of
the last second the loop was held (teal for blocking I/O, orange for CPU, pink for the GIL, purple
for GC), its outline red while the loop runs late; under it its state and lag, `BLOCKED 420ms`
counting up during a stall, or `BUSY +663` when calls pile up in the executors. Press `v` (or
`--view cluster`) for the process: the loop is the first node (green, red while blocked, dark while
killed), then every worker of every pool, dim while idle, teal on I/O, orange on CPU, pink while it
holds a call but waits for the GIL (a thread) or a core (a process); requests fly to the loop, and
calls from the loop to the worker that runs them. Under it: each pool's busy/size +queued. The chart
shows the loop's worst lag each second, coloured by what held it.

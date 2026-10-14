# Lab: autoscaling

*[Leer en español](es/README.md)*

Users send ~120-230 requests/s: the traffic follows a compressed **day** (busy at 1:00, quiet at
6:00, a "day" every 10 minutes), drifts, and comes in short bursts. A load balancer spreads it
over a **fleet of instances**; a warm instance does ~20 requests/s (2 at a time, ~100 ms each)
and queues the rest, and a user whose request waits 2 s gives up (a 504).

Every 10 s the scenario calls your `Autoscaler.desired(metrics)` with the last 10 s of metrics
(`rps`, `cpu`, `in_flight`, how many instances you have, how many are `booting` or `warming`)
and launches or terminates instances to reach the number you return (2 to 40). A new instance
**boots for 20-35 s** (paid for, serving nothing), then **warms up**: 2x slower at first (cold
caches, a cold JIT), warm after 20 s. **Cost** is instance-seconds, booting ones included.

At random times, like in production: the traffic **surges** 1.5-1.9x over a minute (a TV ad, a
marketing email, a viral post, a flash sale), **drops** to 40-60% (traffic fails over to another
region, an upstream outage, a broken mobile release), the **CPU gets noisy** (a batch job, a
backup, a log shipper on the same hosts: CPU reads +30-50%, the capacity does not change) or a
**cold-start wave** restarts the instances batch by batch (a rolling deploy, a config push, a
host rotation: each one is cold again). The first incident is always a **2x surge at 0:20-2:00**.
The fleet at 0:00 was sized by hand for the morning (65% busy). The run never restarts.

```
uv run python -m live autoscaling            # watch it; edit main.py and save
uv run python -m live autoscaling --lesson   # the concept, links and a checklist
uv run pytest labs/autoscaling               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see (the first surge) |
|---|---|---|
| 0 Fixed fleet (given) | `desired` returns the fleet you have | the surge overloads it: 45-75% served, p99 2 s (timeouts), 8-35% less capacity than traffic at its end; at 6:00 over 60% of it idles |
| 1 CPU thresholds | `cpu_step(cpu, instances)`: +1 above 70% CPU, -1 below 30% | one light-orange instance per tick, always behind: p99 0.4-2 s, up to 14% timeouts, headroom -3% to +31% at the end. Later, a noisy batch job adds instances for nothing (cost +86-102%) |
| 2 Target tracking | `target_tracking(m)`: `ceil(rps / TARGET_RPS)`; `stabilised(t, want)`: scale in only after 40 s | whole batches boot at once: 100% served, p99 ~0.3 s, headroom +71-103%, 0 flaps, cost +15-19% |

Goals, judged per incident: baseline ok (before), served ≥ 99% and p99 < 1 s (during), headroom
≥ 50% over the last 20 s of the incident (spare capacity over the traffic; the target is 100%,
since `TARGET_RPS` is half of what an instance can do), flaps ≤ 2 (instances added and removed
again within 30 s, from the start of the incident to 60 s after it) and cost ≤ ideal +50%
(instance-seconds over a fleet that tracks the traffic exactly at `TARGET_RPS`, over the same
span). The stage is judged from the first surge: a fleet that never grew is stage 0; one that
grew but missed a goal is stage 1.

Why both parts of stage 2 matter: without warm-up accounting (`m.instances + needed - m.serving`)
every tick orders again the instances still booting, and the same surge costs +31-43% instead of
+15-19%. Without the stabilisation window every burst adds instances and the next dip removes
them: 2-7 flaps on the first surge, against 0.

**The pictures.** The window opens on the lanes: users → the load balancer (the door: shut red
while requests time out) → the fleet as one server, its gauge the number of instances out of 40
(light orange while some boot, purple while some warm up), its outline red while it has less
capacity than the traffic; under it, its state and the instances serving + booting. Press `v`
(or `--view cluster`) for the fleet itself: one node per instance slot, dim when empty, light
orange while booting, purple while warming up, blue when warm, red while its queue grows;
requests fly to the instance that got them. The chart shows the fleet each second in the same
colours, and in red the instances it lacks at the target.

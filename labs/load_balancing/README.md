# Lab: load balancing

*[Leer en español](es/README.md)*

Users send ~250 requests/s (drifting slowly). Each request reaches one of **4 load
balancers**, and that balancer's `Balancer.pick()` chooses one of **8 servers**. A server
works on 4 requests at once (~40 ms each) and queues the rest; a request not answered
within **1 s** times out (a 504), and the server, which cannot tell, still works on it.
A balancer knows the servers' loads only from a **load report**: every 0.5 s, each
balancer at its own moment, it reads each server's average number of requests in flight
over the half second before. Between reports its view is stale.

At random times, like in production, one server **turns slow** 3.5-5x (a noisy neighbour,
a GC storm, a failing disk, a degraded availability zone) or is **replaced by a cold one**
that starts 5-9x slower and warms up (the autoscaler, a reclaimed spot instance, a rolling
deploy). The first incident is always server s2 turning 5x slower at 0:20-0:32. The run
never restarts: queues, load reports and the clock carry on.

```
uv run python -m live load_balancing            # watch it; edit main.py and save
uv run python -m live load_balancing --lesson   # the concept, links and a checklist
uv run pytest labs/load_balancing               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Round robin (given) | the next server in turn | the slow server gets its full 12.5%; its queue grows and ~11% of all requests time out |
| 1 Least outstanding | `least_outstanding(loads)`: the server with the fewest in flight | the slow server gets ~6%, but each balancer herds: for half a second it sends everything to the one server that looked idle, and when that is the slow one the burst times out (p99 ~1 s, 1-2% timeouts) |
| 2 Power of two choices | `two_choices(loads, rng)`: the less loaded of two random servers | the slow server gets ~5%, no herds, no timeouts, p99 ~0.5 s |

Goals, judged per incident: baseline ok (before), the slow server's share of requests ≤ 10%
(during; a fair share is 12.5%), p99 latency < 750 ms (during), ≥ 99% served without a timeout
(during), ≥ 95% of requests started in the 5 s after served within 750 ms (after).

Why two random choices beat the least loaded server: with fresh data the least loaded is
best, but with stale data every balancer agrees on the same "best" server until the next
report, and sends it everything. Two random choices still never pick the busiest server,
yet spread the rest of the traffic over every server that is not busy. Try three choices:
they herd a little again.

**The pictures.** The window opens on the cluster: the 4 balancers on the top row, the 8
servers below (blue, then orange as their queue grows; the slow one purple), each request
flying from the users to a balancer and on to the server it picked. A herding balancer turns
orange; timeouts die in red. Press `v` (or `--view lanes`) for the users' view: users → the
balancers (the door: orange while one herds, shut red while requests time out) → the fleet,
whose gauge is the busiest server's queue.

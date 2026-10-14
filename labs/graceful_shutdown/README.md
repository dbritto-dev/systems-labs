# Lab: graceful shutdown

*[Leer en español](es/README.md)*

Users send ~300 requests/s (drifting slowly) to **6 instances** of an app behind a **load
balancer** with 3 nodes. The balancer passes connections through: it picks an instance,
round robin, only when a client opens a connection. 60% of requests come on connections
clients keep open (**keep-alive**), and users keep ~100 **streams** open (WebSockets,
server-sent events) for minutes. Each balancer node checks each instance's readiness every
**2 s**, takes it out of rotation after **3 failed checks** in a row, and needs **1 s** more
to apply it. A connection sent to an instance that is not listening is refused: an error.

At random times, like in production, instances are stopped: a **rolling deploy** replaces
all 6 one by one (a release, a config change, a patched base image, a rollback), a **node
is drained** (a kernel patch, a node upgrade, a spot instance reclaimed with a 2-minute
notice) or the **autoscaler scales in**. Each time the orchestrator sends **SIGTERM**,
starts the replacement (it boots in 4 s; then the next old instance gets SIGTERM) and kills
the old one with **SIGKILL 30 s** after SIGTERM. Your `on_sigterm(server)` decides what
happens in between. The first incident is always a rolling deploy at 0:20. The run never
restarts.

```
uv run python -m live graceful_shutdown            # watch it; edit main.py and save
uv run python -m live graceful_shutdown --lesson   # the concept, links and a checklist
uv run pytest labs/graceful_shutdown               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Exit at once (given) | `server.exit()` | ~50 requests and streams cut per instance (~290 per deploy), and for 5-7 s the balancer still sends 1 new connection in 6 to an instance that is gone: ~10% errors; when the next instance stops before the new one is in rotation, only 4 of 6 serve |
| 1 Drain | `drain(server, deadline)`: stop accepting, close idle connections, wait for in-flight work (with a deadline), exit | nothing is cut, each instance exits in ~4 s, but its closed listener refuses what the balancer still sends: still ~10% errors, 4 of 6 serving |
| 2 Readiness off first | `shutdown(server)`: fail readiness, sleep until the balancer has taken it out, then drain | no errors, nothing cut, 5 of 6 serving, each instance gone in ~12 s, well before the kill |

Goals, judged per incident: baseline ok (before: ≤ 0.1% errors), errors ≤ 0.1% of the requests
started during it, requests and streams cut mid-flight = 0, at least 5 of 6 instances serving
(in the balancer and accepting) at every moment (during), and every instance it stopped exited
before the hard kill (after).

Why the order matters: a closed listener cannot tell the balancer anything, it can only refuse
connections. The readiness check is the one channel to the balancer, and it takes checks ×
interval plus the balancer's own delay to work, here 3 × 2 s + 1 s = 7 s. Serve normally
during that time, then drain. Try sleeping exactly 6 s: the errors come back, a few at a time.

**The pictures.** The window opens on the lanes: users → the load balancer (the door: orange
while it still holds an instance that got SIGTERM, shut in red while requests fail) → the fleet,
whose gauge is how many of the 6 instances serve. Requests to an old instance fly orange,
failed ones big and red. Press `v` (or `--view cluster`) for the cluster: the 3 balancer nodes on
the top row, the 6 instance slots below: blue serving, purple starting, orange shutting down,
red while the balancer still sends it connections it refuses, grey once gone; refused and cut
requests die in red.

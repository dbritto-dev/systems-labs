# Lab: failure detection

*[Leer en español](es/README.md)*

How a cluster agrees on who is dead, the way Cassandra, Akka, Consul and Serf do it, in Python on
a simulated network: 8 nodes, ~50 ms per message. Every node runs your `Detector` and keeps
`self.status`: what it thinks of every other node (`"alive"`, `"suspect"` or `"dead"`). A node is
out of the cluster as soon as one healthy node declares it dead, and clients are routed by that
view: each session has a home node, failed over to the next node when the view says it is dead.

The network is never clean: four links (n0-n5, n1-n7, n3-n6, n4-n7) run through an old switch and
lose half of their messages. On top of that, incidents come at random, like in production: a node
crashes (and restarts), gets slow (every message to or from it takes 3-5x longer), loses 15-30% of
its messages, or is cut off from 2 or 3 of the others while the rest still reach it (a partial
partition). Only the crash should end with a death. The first incident always crashes n2 at
0:20-0:30.

```
uv run python -m live failure_detection            # watch it; edit main.py and save
uv run python -m live failure_detection --lesson   # the concept, links and a checklist
uv run pytest labs/failure_detection               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Fixed timeout (given) | heartbeats to everyone every 0.25 s, dead after 1 s of silence | the nodes behind the lossy links keep turning red; with a 3 s timeout, crashes are found 3 s late |
| 1 Phi accrual | `phi(intervals, elapsed)`: judge each silence by that peer's history | crashes found in under a second, lossy links tolerated; but 28 messages per node per second, and a partial partition still buries a node |
| 2 SWIM | ping one peer per period, `ping_req` through K helpers, suspect before dead | a few messages per node; indirect probes go around broken links |

Goals, judged per incident: a crash is declared dead within 2.5 s (by some healthy node), no
healthy node is declared dead from 15 s before the incident to 5 s after it, and each node sends
fewer than 10 messages per second (in the 15 s before it).

Two pictures (key `v`): **cluster**, each node in the colour the cluster gives it (blue alive,
orange suspected, red declared dead, grey crashed but not noticed yet), probes in blue, indirect
probes in light orange, lost messages in red; and **lanes**, what the clients see: green answers
from the home node, light orange after a failover from a dead node, deep orange after a needless
failover from a healthy node declared dead, red when the home node crashed and the router did not
know yet.

The checker reads every node's `self.status` every 250 ms, outside the network. The cluster has
been up for 30 s when the run starts at 0:00, so the detectors have a history to learn from. A
node that comes back from a crash gets 3 s to rejoin before its view counts.

How your node talks is in `core/net.py`: `self.send`, `self.reply`, `await self.rpc`,
`self.every`, `self.spawn`, `self.now()`, and `on_<type>` handlers.

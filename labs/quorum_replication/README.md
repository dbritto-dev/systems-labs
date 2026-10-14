# Lab: quorums

*[Leer en español](es/README.md)*

Leaderless replication, the way Amazon Dynamo, Cassandra and Riak do it, in Python on a
simulated network: 5 nodes, ~100 ms per message. Every key lives on 3 of them (N=3). Clients
send `put` and `get` to any healthy node, which coordinates the request. Incidents come at
random, like in production: a node crashes (and comes back with its old data), is cut off by
the network, or gets very slow. The load balancer stops sending clients to it, but it is still
a replica for 3/5 of the keys. The first incident always crashes n2 at 0:20-0:30.

```
uv run python -m live quorum_replication            # watch it; edit main.py and save
uv run python -m live quorum_replication --lesson   # the concept, links and a checklist
uv run pytest labs/quorum_replication               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 One copy (given) | each node keeps what it is sent | reads land on other nodes and miss the latest write |
| 1 Quorums | write to W=2 of 3 replicas, read from R=2, newest version wins | no stale reads, even with a node down; but it comes back behind |
| 2 Quorums + repair | hinted handoff (and read repair) | the node that came back catches up within seconds |

Goals, judged per incident: stale reads = 0 (from 15 s before it to its end), answered ≥ 99%
of requests during it, ≥ 99% of keys in sync on all their replicas 10 s after it ends, and
fewer than 10 messages between nodes per client operation (in the 15 s before it).

A read is *stale* when it returns an older value than one whose write was acknowledged
before the read started. A key is *in sync* when its 3 replicas hold the same value; the
checker looks at each node's `self.store` every 250 ms, outside the network, and skips keys
written in the last second. Read repair alone is not enough for stage 2: it only fixes the
keys someone reads.

How your node talks is in `core/net.py`: `self.reply`, `self.send`, `await self.rpc`,
`self.every`, `self.spawn`, `self.now()`, and `on_<type>` handlers.

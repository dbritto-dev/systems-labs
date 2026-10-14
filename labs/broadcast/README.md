# Lab: broadcast (Fly.io Gossip Glomers #3)

*[Leer en español](es/README.md)*

[Gossip Glomers](https://fly.io/dist-sys/) challenge #3, in Python, on a simulated network:
25 nodes, ~100 ms per message. Clients send each node `broadcast` (a new number) and `read`
(which numbers do you have?). Every number must reach every node. Network partitions come at
random, like in production; the first one always splits the cluster at 0:20-0:30.

```
uv run python -m live broadcast            # watch it; edit main.py and save
uv run python -m live broadcast --lesson   # the concept, links and a checklist
uv run pytest labs/broadcast               # x = not yet, X = done
```

Two pictures: `cluster` (the default: the nodes and the messages between them) and `lanes`
(what the clients see: their requests waiting, the network as a door, the cluster as one
server). Press `v` to switch, or start with `--view lanes`.

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | Challenge | In `main.py` | What you see |
|---|---|---|---|
| 0 Single node (given) | 3a | keep the numbers you are sent | only one node has each number |
| 1 Multi-node | 3b | tell your neighbours about new numbers | numbers spread, but those sent during a partition are lost |
| 2 Fault tolerant | 3c | re-send until acknowledged | survives partitions, but ~60 msgs/op and ~700 ms |
| 3 Efficient | 3d | fewer hops (e.g. straight to every node) | < 30 msgs/op, p50 < 400 ms, max < 600 ms |
| 4 Batched | 3e | many numbers per message | < 20 msgs/op (p50 < 1 s, max < 2 s) |

Goals, judged per partition: every node gets every number (measured in the calm before it),
numbers sent during it are everywhere 5 s after it heals, messages per operation < 30 and < 20,
and the time until every node has a number (median/max) < 400/600 ms and < 1/2 s.

Messages per operation counts messages between nodes, divided by client operations (reads
included), like Maelstrom's `msgs-per-op`. The checker looks at each node's `self.messages`
every 20 ms, outside the network, so it never adds traffic.

How your node talks is in `core/net.py`: `self.reply`, `self.send`, `await self.rpc`,
`self.every`, `self.spawn`, `self.now()`, and `on_<type>` handlers.

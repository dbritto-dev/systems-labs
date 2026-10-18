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
| 0 Nothing yet (given) | | | every request gets an error |
| 1 Single node | 3a | keep the numbers you are sent, answer `read` | only one node has each number |
| 2 Multi-node | 3b | tell your neighbours about new numbers (not your whole set) | numbers spread, but those sent during a partition are lost |
| 3 Fault tolerant | 3c | re-send until acknowledged | survives partitions, but ~60 msgs/op and ~700 ms |
| 4 Efficient | 3d | fewer hops (e.g. straight to every node) | < 30 msgs/op, p50 < 400 ms, max < 600 ms |
| 5 Batched | 3e | many numbers per message | < 20 msgs/op, p50 < 1 s, max < 2 s: slower than stage 4 is fine |

Goals, judged per partition: the clients' requests are answered right (≥ 99%), every node gets
every number, a message between nodes carries under 30 numbers on average (all measured in the
calm before it), numbers sent during it are everywhere 5 s after it heals, messages per
operation < 30 and < 20, and the time until every node has a number (median/max) < 400/600 ms
and < 1/2 s.

Messages per operation counts messages between nodes, divided by client operations (reads
included), like Maelstrom's `msgs-per-op`. Numbers per message counts the numbers in each
message between nodes (a list counts its length), so a node that sends its whole set, which
grows by ten numbers a second, fails it, as Fly.io's 3b asks. The checker looks at each node's
`self.messages` every 20 ms, outside the network, so it never adds traffic. The clients check
every reply, like Maelstrom: a `read_ok` must list every number the node had when the read was
sent, and only numbers that were broadcast; anything else is a failed read.

How your node talks is in `core/net.py`: `self.reply`, `self.send`, `await self.rpc`,
`self.every`, `self.spawn`, `self.now()`, and `on_<type>` handlers.

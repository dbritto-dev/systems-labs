# Lab: Kafka log (Fly.io Gossip Glomers #5)

*[Leer en español](es/README.md)*

[Gossip Glomers](https://fly.io/dist-sys/) challenge #5, in Python, on a simulated network:
two nodes and Maelstrom's `lin-kv`, ~10 ms per message. Clients (~30 operations/s) talk to
either node: `send` appends a message to a key's log and gets its offset, `poll` reads from an
offset on, `commit_offsets` and `list_committed_offsets` track how far consumers got.

Incidents come at random, like in production: a burst of sends to one hot key (2-2.5x the
traffic), or lin-kv slowing down 2-4x. The first one is always a burst at 0:20-0:30.

```
uv run python -m live kafka_log            # watch it; edit main.py and save
uv run python -m live kafka_log --lesson   # the concept, links and a checklist
uv run pytest labs/kafka_log               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | Challenge | In `main.py` | What you see |
|---|---|---|---|
| 0 Single node (given) | 5a | each node keeps its own log | duplicate offsets, lost writes, lost commits |
| 1 Multi-node | 5b | offsets and messages in lin-kv (a CAS counter per key) | no anomalies, but ~10 msgs/op and p99 sends of 300-700 ms in a burst |
| 2 Efficient | 5c | fewer round trips (e.g. an owner node per key) | ~1.3 msgs/op, p99 send ~47 ms, even in bursts |

Goals, judged per incident: offsets unique (15 s before it), no lost writes (during),
committed offsets kept (10 s after), messages per operation < 3 (before; between the nodes
and lin-kv, divided by client operations), and p99 send < 100 ms (during).

The checker watches every reply, like Maelstrom's kafka checker: two acknowledged sends with
the same offset for a key; a poll that returns an offset but skips an earlier acknowledged one
(or returns a different message at it); a listed committed offset lower than an acknowledged
commit.

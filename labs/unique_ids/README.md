# Lab: unique IDs (Fly.io Gossip Glomers #1-2)

*[Leer en español](es/README.md)*

[Gossip Glomers](https://fly.io/dist-sys/) challenges #1 (Echo) and #2 (Unique ID Generation),
in Python, on a simulated network: 5 nodes, ~100 ms per message. Clients send `echo` and
`generate` to random nodes. Incidents come at random, like in production: the network between
the nodes partitions, a node's clock steps back (NTP), or a VM migration does both. The first
one is always a migration at 0:20-0:30.

```
uv run python -m live unique_ids            # watch it; edit main.py and save
uv run python -m live unique_ids --lesson   # the concept, links and a checklist
uv run pytest labs/unique_ids               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Nothing yet (given) | no handlers | every request gets an error |
| 1 Echo | `on_echo` replies `echo_ok` | echo works; no ids yet (a counter per node gives duplicates; asking a leader stops in a partition) |
| 2 Unique IDs | `on_generate`: node + counter | unique and available, but not a sortable 64-bit key |
| 3 Snowflake IDs | ms \| node \| sequence, never going back | unique, 64-bit, time-ordered, survives clock jumps |

Goals, judged per incident: echo works; no duplicate ids (15 s before it, and during it);
generate answered ≥ 99% during it; ids are 64-bit ints and time-ordered (an id is larger than
every id handed out at least 1 s before) in the calm before it; no node's ids go backwards
during it.

Each node reads its wall clock with `self.wall_ms()`; the scenario can step it back.

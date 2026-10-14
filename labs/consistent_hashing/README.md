# Lab: consistent hashing

*[Leer en español](es/README.md)*

Users read ~500 keys/s (drifting slowly, a few keys far more popular than the rest) from 8
cache servers in front of a slow database (10 ms a read, 4 at a time: about 400 reads/s).
Your `Router.node_for(key)` picks the server for every read; a hit answers at once, a miss
goes to the database and fills that server's cache. At random times, like in production,
the cluster changes: a node dies (kernel panic, spot instance reclaimed, OOM…) and is
replaced later with an empty cache, the autoscaler adds a ninth node for a while, or a
deploy restarts one. The run never restarts. The first change is always a node dying at 0:20.

```
uv run python -m live consistent_hashing          # watch it; edit main.py and save
uv run python -m live consistent_hashing --lesson # the concept, links and a checklist
uv run pytest labs/consistent_hashing             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Modulo (given) | `hash(key) % N` | a change moves ~7/N of the keys: misses turn the dots red, hits drop to ~60% of before, the database reads ~2.5x |
| 1 Hash ring | one point per node on a ring; a key goes to the next point clockwise | a change moves ~1/N, but the busiest node owns 1.9x the average |
| 2 Ring + virtual nodes | 200 points per node | ~1/N moves, the busiest node owns 1.16x; every goal OK |

Goals, judged per change:

- **Keys/node ≤ 1.4x** (before): keys on the busiest node vs the average, in the cluster as it
  was just before the change.
- **Moved ≤ 3/N** (during): of 2,000 sample keys, how many go to a different node after the
  change, in units of 1/N (N the bigger cluster). The ideal is 1/N; modulo is ~7/N. A ring with
  one point per node can move up to ~2.5/N when a node with a big arc leaves.
- **Hits kept ≥ 90%** (after): the hit ratio in the 4 s after the change vs the 15 s before.
- **DB load ≤ 2x** (after): database reads/s in the 4 s after the change vs the 15 s before.

The stage comes from the first change: keys moved and the spread, which your router decides.
Hits and database load are what users and the database feel; they follow.

Every change is measured where it happens: the scenario asks your router where the sample keys
go just before and just after `add` or `remove`. Use a stable hash (`stable_hash`, md5):
Python's own `hash()` of a string changes from one process to the next.

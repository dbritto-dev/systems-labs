# Lab: hedged requests

*[Leer en español](es/README.md)*

Users send ~100 reads/s through your `Client`. Every key is on 3 replicas, and any of them
can answer. A reply takes ~10 ms (p95 ~14 ms), but 1 in 50 takes 100–400 ms anyway: a GC
pause, a cache miss, a slow disk. Rare for one call, but it is exactly what the p99 user
sees. At random times, like in production, one replica gets much slower for a while,
0.2–0.8 s a reply (a compaction, a noisy neighbour, a degraded volume, a backup snapshot),
or every replica gets a few times slower (a hot key, cold caches after a deploy). Users
give up after 1 s. The first incident is always replica 2, 0.5 s a reply, at 0:20–0:30.

```
uv run python -m live hedged_requests            # watch it; edit main.py and save
uv run python -m live hedged_requests --lesson   # the concept, links and a checklist
uv run pytest labs/hedged_requests               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 One call (given) | ask one replica, wait as long as it takes | p99 ~150–270 ms with nothing wrong: the rare slow replies set it |
| 1 Hedge | after `HEDGE_AFTER` (20 ms) with no answer, send a copy to another replica; the first answer wins | p99 ~30 ms, for ~2% more calls; but a slow replica costs a copy per read sent to it (+35%; +100% when all are slow), and its losers keep running (~85% of its time wasted) |
| 2 Hedge + budget + cancel | a `HedgeBudget` (5% of reads, 10 tokens) pays for each copy; cancel the loser | copies stay at +6–7% in any incident, nothing wasted; while one replica stays slow, reads sent to it wait (the budget's price) |

Goals, judged per slowdown: p99 ≤ 50 ms (before); extra calls ≤ 10% of reads (during);
replica time wasted on calls nobody waits for ≤ 5% (during); served ≥ 99% (during);
p99 ≤ 50 ms again from 3 s after it is over (after, so the budget must refill).

The chart shows the copies sent each second, against 10% of the traffic.

**Two pictures.** It opens with **cluster**: the service (where your `Client` runs) and the 3
replicas. Reads fly in white; calls fly to a replica, white for the first and orange for a copy.
A call that takes long parks by its replica, light orange while its read waits for it, and deep
orange once the other copy has answered and nobody cancelled it: wasted work. A slow replica
turns orange. Press `v` (or `--view lanes`) for **lanes**: users turn light orange while their
read is slow and orange once a copy is sent (big orange dots fly to the door); the door is the
hedge budget, shut while slow reads get no copy, and the gauge is the calls per read.

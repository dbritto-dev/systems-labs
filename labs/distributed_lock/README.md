# Lab: distributed lock

*[Leer en español](es/README.md)*

Four workers share one report in a storage service, and only one job may write it at a time, so
a job first takes a lock from a lock service: the problem of Martin Kleppmann's
[How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html),
in Python on a simulated network (~50 ms per message). Clients hand out ~0.8 jobs a second to any
healthy worker; the worker takes the lock, writes the report in 3 parts, releases it and answers.
Incidents come at random, like in production, and hit the job that holds the lock at the worst
moment: it **freezes** (a GC pause, a VM migration, swapped out), **crashes** with the lock, its
**write sits in the network** (TCP retransmits, a congested link), or it is **cut off** from the
lock service. The first incident is always a 10 s pause, from the first write after 0:20.

```
uv run python -m live distributed_lock            # watch it; edit main.py and save
uv run python -m live distributed_lock --lesson   # the concept, links and a checklist
uv run pytest labs/distributed_lock               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Plain lock (given) | the lock is held until released | a frozen holder stalls every job for the whole pause (~10.8 s); a crashed or cut-off one, forever |
| 1 Leases | the lock expires `LEASE` (2 s) after its grant or last renewal; the holder renews every `LEASE / 3` | stalls of 2.4–4.2 s; but when the frozen holder wakes, its write lands on newer data: 1 corrupt write per pause or late write |
| 2 Leases + fencing tokens | every grant carries a token one higher; writes carry it; the storage refuses an older one | the same late write is refused: 0 corrupt writes, stalls bounded, ~100% of jobs done |

Goals, judged per incident: corrupt writes = 0 (from 15 s before it to 10 s after), stuck ≤ 5 s
(the longest stretch with jobs waiting and none finishing, from its start to 10 s after), and
jobs done ≥ 80% (of those asked for in that span; a client gives up after 10 s).

A write is *corrupt* when the storage accepts it after a job that got the lock later has already
had a write accepted: the checker watches the `acquire_ok` and `write_ok` messages, outside your
code. Checking your own clock before writing does not help: a pause hits right after a worker
decides to write, the way Kleppmann describes it.

The chart shows the lock messages (polling while the lock is taken: a hump means jobs are
stuck) and the writes, each second.

**Two pictures.** It opens with **cluster**: the lock service (top left), the storage (bottom
left) and workers w1..w4. Lock messages fly in blue and writes in white (light orange while one
sits in the network); the holder is green, a frozen worker orange (its writes wait just outside
it), a dead or cut-off one red. A late write the storage accepted bursts red by it, one it
refused bursts orange; under the grid, the state and who got the lock last. Press `v` (or
`--view lanes`) for **lanes**: jobs wait for the lock (the door, shut while it is stuck) in front
of the storage; late writes land red (accepted) or orange (refused).

How your nodes talk is in `core/net.py`: `self.reply`, `self.send`, `await self.rpc`,
`self.spawn`, `self.now()`, and `on_<type>` handlers.

# Lab: grow-only counter (Fly.io Gossip Glomers #4)

*[Leer en español](es/README.md)*

[Gossip Glomers](https://fly.io/dist-sys/4/) challenge #4, in Python, on a simulated network:
3 stateless nodes on a LAN (20 ms per message) and Maelstrom's `seq-kv` service, a key/value
store that is *sequentially consistent*: a read may return a value up to 0.5 s old, though
never older than your own writes. Clients send `add` (a delta) and `read` (the total).

Incidents come at random, like in production: bursts of adds (a flash sale, a client stuck
in a retry loop), a slow network, and partitions, as in Fly.io's `--nemesis partition`: one
node cut off from the other two (it still reaches seq-kv, a service, as in Maelstrom). The
first one is always a 3x burst at 0:20-0:30.

```
uv run python -m live grow_only_counter            # watch it; edit main.py and save
uv run python -m live grow_only_counter --lesson   # the concept, links and a checklist
uv run pytest labs/grow_only_counter               # x = not yet, X = done
```

Two pictures: `cluster` (the default: the nodes and the messages between them) and `lanes`
(what the clients see: their requests waiting, the network as a door, the cluster as one
server). Press `v` to switch, or start with `--view lanes`.

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 In memory (given) | each node counts its own adds | seq-kv gets nothing; every read is too small |
| 1 Shared key | read `counter`, add, write it back | nodes overwrite each other: reads miss acknowledged adds |
| 2 Compare-and-swap | `cas` and retry on code 22 | nothing lost, but 80-99% of CAS conflict; in a burst adds time out |
| 3 Key per node | each node writes only its own key; a read adds them up | no conflicts; every read right |

Goals, judged per incident: the count lives in seq-kv (before), no lost adds (before),
conflicts < 10% of compare-and-swaps (during), adds answered ≥ 99% (during), reads right
again 2-7 s after it (after).

A read is *right* when its value is at least every add acknowledged 1.5 s before the read
started (seq-kv may lag 0.5 s) and at most every add sent before it ended. In the picture
seq-kv is the purple node; conflicts flash red on their way back from it.

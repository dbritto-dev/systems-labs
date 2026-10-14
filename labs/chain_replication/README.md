# Lab: chain replication

*[Leer en español](es/README.md)*

A key/value store kept on 4 nodes (`n0`..`n3`) on a simulated network (~30 ms per message). A
configuration master (assume it is reliable, like ZooKeeper or etcd) holds the chain, head first,
and sends every node the new chain when it changes. Clients send ~10 writes a second to the head
and ~10 reads a second to the node `read_from(chain, rng)` picks.

Incidents come at random, like in production: the head, the tail or a middle node crashes (a
kernel panic, an OOM kill, a disk failure…; the master drops it from the chain when its session
times out, 1 s later), or a node turns slow and backs the chain up (GC pauses, a full disk, a noisy
neighbour; the master ejects it after 2 s and fences it, so it restarts empty). When the incident
ends the node comes back empty and joins again: the master asks it to copy the tail's state (the
copy takes ~1 s on the wire), then adds it as the new tail. The run never restarts. The first
incident always crashes the middle node `n1` at 0:20; it is back at 0:30.

```
uv run python -m live chain_replication          # watch it; edit main.py and save
uv run python -m live chain_replication --lesson # the concept, links and a checklist
uv run pytest labs/chain_replication             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see (first incident) |
|---|---|---|
| 0 Primary-backup (given) | the head applies a write, answers at once, ships it to the backups every 0.5 s; reads go to any replica | stale reads even while nothing fails (3 to 7 in the first incident's window); a head crash later loses acknowledged writes |
| 1 Chain | `on_put` numbers the write, `on_write` applies in seq order, `apply` passes it on (or, at the tail, answers and acks), `on_ack` forgets; `read_from` returns the tail | nothing stale, nothing lost; when `n1` dies the head keeps sending to `n2`, which waits forever for the writes `n1` took with it: no write succeeds again (15 s of outage) |
| 2 Chain + repair | `chain_changed`: a new head drops its gap, a new tail answers what it sent, a node with a new successor resends what it sent and never saw acked; the tail keeps what it applies while a node copies it | `n0` resends to `n2` and the writes stuck behind `n1` finish (~1.2 s, none fail); `n1` copies the tail and joins as the tail; every goal OK |

Goals, judged per incident: stale reads = 0 (from 15 s before it until the node is back), lost
writes = 0 (acknowledged writes no live node of the chain holds, until 5 s after it), write outage
≤ 3 s (seconds in which fewer than 90% of the writes succeeded, from its start until 5 s after it),
in sync = 4 (replicas in the chain, alive, holding every write acknowledged over a second ago, 5 s
after it), and write p99 ≤ 500 ms (the 15 s before it).

A read is *stale* when it returns an older value than a write acknowledged before the read started,
or than a read that ended before it started (a value someone saw cannot go away). The checker reads
every node's `self.store` every 250 ms, outside the network.

- **Why the tail.** A write is acknowledged only once the tail has it, and it passed every node on
  the way: so every node holds every acknowledged write, and the tail holds nothing that is not on
  every node. A read from the tail is always up to date and never sees a value that could be lost.
  Read from the head and you see writes that may still die with it.
- **Why keep what you sent.** Every repair is the same idea: the node before the gap still has the
  writes it passed down until the tail's ack comes back, so it can send them again. That is also how
  a node joins: it copies the tail, and the tail keeps (and then resends) what it applied meanwhile.
- **The price.** Every write crosses every node: latency is the sum of the hops (~160 ms here), and
  a slow node slows every write until the master ejects it (the chart turns orange).
- Variants the tests use: a chain read from any node lands on stage 0 (a read sees a write that the
  dead node takes with it, then a later read does not); a repair whose tail forgets the writes it
  applies during a copy, or a head that waits for each write's ack before sending the next, land on
  stage 1.

How your node talks is in `core/net.py`: `self.reply`, `self.send`, `await self.rpc`,
`self.every`, `self.spawn`, `self.now()`, and `on_<type>` handlers.

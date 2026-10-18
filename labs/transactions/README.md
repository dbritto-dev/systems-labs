# Lab: transactions (Fly.io Gossip Glomers #6)

*[Leer en español](es/README.md)*

[Gossip Glomers](https://fly.io/dist-sys/) challenge #6 (totally-available transactions), in
Python, on a simulated network: 3 nodes, ~100 ms per message. Clients send any node a `txn`,
a list of micro-operations (`["r", key, null]`, `["w", key, value]`); the node answers
`txn_ok` with every read filled in. Write values are unique, and a quarter of the transactions
write one key twice (the first value is *intermediate*). Two hot keys get half the operations.

Partitions come at random, like in production: one node is cut off from the other two; the
clients still reach it, so every transaction must still be answered (total availability).
The first one always cuts a node off at 0:20-0:30.

```
uv run python -m live transactions            # watch it; edit main.py and save
uv run python -m live transactions --lesson   # the concept, links and a checklist
uv run pytest labs/transactions               # x = not yet, X = done
```

Two pictures: `cluster` (the default: the nodes and the messages between them) and `lanes`
(what the clients see: their requests waiting, the network as a door, the cluster as one
server). Press `v` to switch, or start with `--view lanes`.

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | Challenge | In `main.py` | What you see |
|---|---|---|---|
| 0 Single node (given) | 6a | each node keeps its own store | the nodes are always behind (~45% fresh) |
| 1 Replicated | 6b, no partitions | send every write to the other nodes | fresh, but after a partition some keys never catch up (~90-95%), and writes interleave (G0) |
| 2 Read uncommitted | 6b, with partitions | re-send until acked; newest stamp (one per transaction) wins | everyone catches up, no G0, but readers see intermediate values (G1b) |
| 3 Read committed | 6c | replicate whole transactions (final values), applied at once | no G0 and no G1a, G1b or G1c, and every node catches up |

Goals, judged per partition: **fresh** ≥ 95% in the calm before it (the share of keys, on every
node, within 1 s of the newest value anywhere); **answered** ≥ 99% of transactions during it;
**caught up** ≥ 99% fresh 5-10 s after it heals; **no G0 writes** (stage 2) and **no G1 reads**
(stage 3), both from 15 s before it to 5 s after.

The checker looks at each node's `self.store` every 50 ms, outside the network, and checks
what Fly.io's 6b and 6c forbid:
- **G0, dirty write** (read uncommitted already forbids it): it notes every write to a store as
  it happens; two transactions that both wrote x and y, applied T then U on x but U then T on y
  on some node, interleaved their writes. One stamp per transaction rules it out.
- **G1a, aborted read**: a node may abort a transaction (error code 30, `txn-conflict`); a later
  read that returns one of its writes is a G1a.
- **G1b, intermediate read**: a read that returns a value another transaction overwrote itself.
- **G1c, circular information flow**: two transactions that each read the other's write. Only
  cycles of two are checked, not longer ones.

Every answer is checked too, like Maelstrom: a `txn_ok` must carry the same micro-operations in
order, writes echoed and reads filled in; anything else counts as not answered.

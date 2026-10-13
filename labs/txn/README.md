# Lab: txn (Fly.io Gossip Glomers #6)

[Gossip Glomers](https://fly.io/dist-sys/) challenge #6 (totally-available transactions), in
Python, on a simulated network: 3 nodes, ~100 ms per message. Clients send any node a `txn`,
a list of micro-operations (`["r", key, null]`, `["w", key, value]`); the node answers
`txn_ok` with every read filled in. Write values are unique, and a quarter of the transactions
write one key twice (the first value is *intermediate*). Two hot keys get half the operations.

Partitions come at random, like in production: one node is cut off from the other two; the
clients still reach it, so every transaction must still be answered (total availability).
The first one always cuts a node off at 0:20-0:30.

```
uv run python -m live txn            # watch it; edit main.py and save
uv run python -m live txn --lesson   # the concept, links and a checklist
uv run pytest labs/txn               # x = not yet, X = done
```

| Stage | Challenge | In `main.py` | What you see |
|---|---|---|---|
| 0 Single node (given) | 6a | each node keeps its own store | the nodes are always behind (~45% fresh) |
| 1 Replicated | 6b | send every write to the other nodes | fresh, but after a partition some keys never catch up (~90-95%) |
| 2 Read uncommitted | 6b + partitions | re-send until acked; newest stamp wins | everyone catches up, but readers see intermediate values (G1b) |
| 3 Read committed | 6c | replicate whole transactions (final values), applied at once | no intermediate reads, and every node catches up |

Goals, judged per partition: **fresh** ≥ 95% in the calm before it (the share of keys, on every
node, within 1 s of the newest value anywhere); **answered** ≥ 99% of transactions during it;
**caught up** ≥ 99% fresh 5-10 s after it heals; **no G1b reads** from 15 s before it to 5 s after.

The checker looks at each node's `self.store` every 50 ms, outside the network, and checks
every read the clients get back: a read that returns another transaction's intermediate value
is a G1b. It does not look for G0 directly: a single stamp per transaction with last-writer-wins
gives every key the same write order on every node, which is what rules G0 out.

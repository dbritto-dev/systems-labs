# Lab: vector clocks and CRDTs

*[Leer en español](es/README.md)*

Multi-leader replication of shopping carts, in Python on a simulated network: 5 replicas, one
per site, ~100 ms per message. Every replica takes adds and removes from the devices near it
right away (no leader, it works offline) and gossips its carts to the others. A cart is shared
by two devices that talk to two different replicas, so the same cart is edited in two places
at once. Incidents come at random, like in production: the network splits the replicas in two
(both sides keep taking writes), a replica goes offline from the others (its site keeps
serving, and it comes back with old carts plus its own edits), or a replica's clock jumps
ahead or back (an NTP step) so its timestamps lie. The first incident always splits {n0, n1}
from {n2, n3, n4} at 0:20-0:30.

```
uv run python -m live vector_clocks_crdts            # watch it; edit main.py and save
uv run python -m live vector_clocks_crdts --lesson   # the concept, links and a checklist
uv run pytest labs/vector_clocks_crdts               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Last write wins (given) | each cart is one value stamped with the wall clock; the newest stamp wins | when the network heals, one side's adds vanish; a clock jump loses adds with no partition at all |
| 1 Vector clocks | `compare`, `keep_newest`: concurrent versions become siblings, merged (a union) on read | no add is lost, but removed items come back from a sibling that still had them |
| 2 CRDT | `ORSet`: a unique tag per add, a remove tombstones the tags it has seen, merge is a union | replicas diverge during a split and agree within a second of the heal; nothing lost, nothing back |

Goals, judged per incident: lost adds = 0 and removed items back = 0 (from the start of the
incident to 10 s after it ends), ≥ 99% of carts the same on every replica 5 s after it ends,
and at most 150 messages per second between replicas (in the 15 s before it).

An add is *lost* when the replica that acknowledged it no longer has the product while the
device still has it in the cart; a remove is *back* (resurrected) when the product shows up
again on the replica that acknowledged the remove. Each device adds and removes only its own
products (6 of the cart's 12), toggling them: a product removed is often added again later, so
tombstones must be per add (a tag), not per product. A cart is *in sync* when `items(cart)` is
the same on all 5 replicas; the checker looks every 250 ms, outside the network, and skips
carts written in the last second.

How your node talks is in `core/net.py`: `self.reply`, `self.send`, `self.every`, and
`on_<type>` handlers. The given code already pushes every change to every peer and gossips
every cart once a second: you change how a cart is stored, written and merged (`items`,
`add`, `remove`, `put`, `state`, `merge`).

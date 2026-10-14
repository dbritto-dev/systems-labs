# Lab: two-phase commit

*[Leer en español](es/README.md)*

A bank keeps its accounts on 3 shards (`n1`, `n2`, `n3`) on a simulated network (~30 ms per
message); the coordinator is `n0`. Clients send ~10 transfers a second. Every transfer touches the
three shards: it takes money from a customer on one, pays a merchant on another and the bank's fee
on the third, and the three amounts add up to zero. Merchants and fee buckets are few, so their rows
are hot: a row left locked blocks the transfers behind it.

Incidents come at random, like in production: a shard votes no for a share of transfers (lock
timeouts behind a long report, a new CHECK constraint, frozen accounts), a shard crashes right after
voting yes (it comes back with its disk: prepare records and their locks), the coordinator crashes
(a deploy or an eviction kills it at once; an OOM kill hits while it sends a commit, so one shard
gets the decision and the others do not), or the network cuts a shard off from the coordinator. The
run never restarts. The first incident is always `n2` busy with lock timeouts at 0:20–0:30; at 0:26
the coordinator, full of waiting transfers, is OOM-killed while it sends a commit, and it is back at
0:29.

```
uv run python -m live two_phase_commit          # watch it; edit main.py and save
uv run python -m live two_phase_commit --lesson # the concept, links and a checklist
uv run pytest labs/two_phase_commit             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see (first incident) |
|---|---|---|
| 0 One shard at a time (given) | write to each shard in turn; stop at the first no | when `n2` says no, the shard before it keeps its write: 22 partial commits, $2,773 created or destroyed (red) |
| 1 Two-phase commit | `two_phase`: prepare everywhere (`vote`), commit only if every vote is yes, else abort; shards `prepare` / `commit` / `abort` | no votes abort on every shard; but the OOM kill leaves `n2` and `n3` in doubt forever (orange), $121 missing, and their locked rows make later transfers time out (56% completed) |
| 2 2PC with recovery | log the commit before sending it, resend until acknowledged, `recover()` resends what the log holds; shards in doubt `ask` the coordinator; `on_status` answers from the log (presumed abort) | shards stay in doubt while the coordinator is down (the price of 2PC), then resolve a moment after it is back; every goal OK |

Goals, judged per incident (transfers started from 1 s before it, since they are still running when
it starts): baseline ok (≥ 95% committed in the 15 s before), no votes undone 100% (transfers a
shard said no to are applied nowhere; "none" if no shard said no), partial commits = 0 (applied on
some shards, aborted on others), money conserved 3 s after it ends (money created or destroyed by
its transfers: $0), in doubt ≤ 3 s after it ends (prepared transfers still waiting for a decision),
and completed ≥ 90% of the transfers started in the 5 s after it.

- **Why a shard cannot decide alone.** Once it voted yes, the others may have committed (the
  coordinator logged commit and sent it to one shard before dying). A shard that aborts after a
  timeout makes that transfer partial. It must hold its locks and ask.
- **Why log before sending.** If the coordinator sends commit and dies before logging it, a new
  coordinator finds no record and answers "abort" (presumed abort) to the shards that ask: the shard
  that got the commit keeps it, the others abort. Partial again.
- **The price.** While the coordinator is down, prepared rows stay locked: the "In doubt" tile is
  orange and the events show how long the rows were held. 2PC is safe, not available.

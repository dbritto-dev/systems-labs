# Lab: raft (leader election and log replication)

*[Leer en español](es/README.md)*

[Raft](https://raft.github.io/), in Python, on a simulated network: 5 nodes, ~20 ms per
message. Clients send `command` (a new number) to the node they think leads; a follower
redirects them. The nodes must agree on one ordered log, answer a client only once its command
is on a majority, and never lose a committed command. Incidents come at random, like in
production: the leader is cut off with one follower, the leader's host crashes and restarts, or
the network gets slow. The first one always cuts the leader off at 0:20-0:30.

```
uv run python -m live raft_consensus            # watch it; edit main.py and save
uv run python -m live raft_consensus --lesson   # the concept, links and a checklist
uv run pytest labs/raft_consensus               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 No leader (given) | keep the state, redirect clients | every node stays blue; every command fails |
| 1 Leader election | random timeouts, RequestVote, heartbeats | a green leader; a new one within ~0.5 s of a split, but acked commands are only on the leader |
| 2 Log replication | AppendEntries, commit on a majority | every command on a majority; after the split heals the old leader overwrites committed entries |
| 3 Safe | step down on a higher term, reject stale leaders, vote only for up-to-date logs | nothing lost, ever |

Goals, judged per incident: a leader in the calm before it (95% of the time), a new leader
within 2 s when it hits the leader, 99% of commands committed in the calm and none acknowledged
without being on a majority, no committed command lost (until 5 s after it ends), and 95% of
commands acknowledged during it.

The checker reads every node's `role`, `current_term` and `log` every 50-100 ms, outside the
network, so it adds no traffic. A command is committed once a majority holds the same entry at
the same position; it is lost if a node that held it no longer does. A crash keeps only what
Raft persists (`current_term`, `voted_for`, `log`). A partition heals one way first: for 0.5 s
the cut-off side is heard before it hears back, which is when a leader that ignores terms does
its damage.

How your node talks is in `core/net.py`: `self.reply`, `await self.rpc`, `self.spawn`,
`self.every`, `self.now()`, and `on_<type>` handlers.

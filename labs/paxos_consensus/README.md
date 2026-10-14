# Lab: paxos (one replicated log, several proposers)

*[Leer en español](es/README.md)*

[Paxos](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf), in Python, on a simulated
network: 5 nodes, ~20 ms per message. They keep a replicated log of config changes: each slot
(0, 1, 2, ...) holds one command. Clients send `command` (a new number) to any node, so several
nodes propose at once. A node answers the client once the command is decided in a slot and
applied (every slot before it decided too). Every node must decide the same command in every
slot, and no answered command may vanish. Incidents come at random, like in production: the
leader crashes in the middle of a round, another node crashes, the network loses and delays
messages, a partition cuts the leader off with one node, or the leader stops for a few seconds
(a GC pause) and wakes up still sure it leads. The first one is always the leader dying mid-round
at 0:20 (back at 0:30).

```
uv run python -m live paxos_consensus            # watch it; edit main.py and save
uv run python -m live paxos_consensus --lesson   # the concept, links and a checklist
uv run pytest labs/paxos_consensus               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 First proposal wins (given) | each node keeps the first value it hears for a slot | purple propose dots race; red nodes: some decided one command, some another |
| 1 Paxos per slot | `on_prepare`, `on_accept`, `submit`, `paxos`: ballots, promises, adopt the highest accepted value | nothing splits, but orange prepares on every command, proposers outbid each other, and 100+ messages per command |
| 2 Multi-Paxos | `campaign`, `phase2`, `on_heartbeat`, `tick`, and redirects in `on_command`: one leader, phase 1 once, no-ops in gaps, random backoff | one green leader; ~13 messages per command; a new leader within a second of a crash |

Goals, judged per incident: one log for all (no slot decided two ways, from 15 s before it
until 5 s after it), nothing lost (every answered command is in the log most nodes decided), 95%
of commands decided within 2 s during it and 5 s after it, and at most 16 messages between nodes
per decided command in the calm before it.

The checker watches every node's `decided` and `accepted` dictionaries (outside the network, so
it adds no traffic): two different values decided in one slot, or a value decided that differs
from the one a majority of acceptors accepted (chosen), is a disagreement. A crash keeps only what
Paxos keeps on disk (`promised`, `accepted`, `decided`). The first crash is staged to hurt: the
leader stops reading the network, one slot's accepts are lost with it, and the next two slots'
accepts reach everyone. Those two are chosen and nobody knows it, with a gap before them: a new
leader must propose them again and fill the gap with a no-op.

How your node talks is in `core/net.py`: `self.reply`, `await self.rpc`, `self.spawn`,
`self.every`, `self.now()`, and `on_<type>` handlers; `main.py` adds `broadcast`, `learn`,
`decide` and the ballot helpers.

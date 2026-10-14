# Lab: replication lag

*[Leer en español](es/README.md)*

A primary database and 4 asynchronous read replicas (r1..r4). ~200 users (sessions) make
~200 operations/s: 15% are writes (their own profile, or one of 20 popular pages), the rest
are reads. Every write commits on the primary and reaches each replica 50–200 ms later. Your
`Router` decides where every read goes, knowing each replica's log position (LSN) as of its
last report, every 100 ms.

At random times, like in production, one replica falls 2–10 s behind (a long analytics
query, autovacuum, a network brownout), a replica restarts and replays what it missed, or a
write spike puts every replica behind. The run never restarts. The first incident is always
r2 falling 6 s behind at 0:20–0:30.

```
uv run python -m live replication_lag          # watch it; edit main.py and save
uv run python -m live replication_lag --lesson # the concept, links and a checklist
uv run pytest labs/replication_lag             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Any replica (given) | read from any replica that is up | during a lag, ~120–230 users miss their own write and ~50–220 pages go back in time |
| 1 Read your writes | remember each session's last write LSN in `wrote`; `pick` only replicas with `lsn >=` it | no missed writes, but ~40–80 pages still go back in time while a replica lags |
| 2 Monotonic reads | also remember the newest version each session saw of each key (`saw`) | nothing goes wrong; the primary takes ~6–8% of reads (~12–21% in a write spike) |

Reading everything from the primary also gets 0 wrong reads, but puts 100% of the reads on
the primary: it fails the third goal and stays at stage 0.

Goals, judged per incident from its start until 5 s after it ends:

- **Own writes = 0**: no read of a user's own profile returns an older version than the
  last write that user had made when the read started.
- **Back in time = 0**: no read returns an older version of a key than the session had
  already seen.
- **Primary ≤ 35%**: at most 35% of the answered reads go to the primary.

The live window shows the primary (top left) and the replicas, coloured by how far behind
they are; blue dots are writes on their way to each replica (a lagging replica has a long
trail of them), white dots are reads, and red blobs are wrong reads.

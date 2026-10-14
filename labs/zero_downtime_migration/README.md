# Lab: zero-downtime migration

*[Leer en español](es/README.md)*

The app keeps each user's name in `users.fullname` (10,000 rows), and the next release
renames it to `users.display_name`. Six app instances serve ~100 requests/s (70% read a
name, 30% change one). A release rolls out one instance every 2 s, so for a while **old**
instances (they read and write the old column) and **new** ones (they run your
`read_name` and `write_name`) share the database. Your `migrate` starts when the window
opens, 2 s before the deploy, and must have dropped the old column within 60 s.

The database's load is the app's traffic (~0.3) plus whatever else runs: your copies,
instances that just restarted (cold caches), a traffic peak, and the reads that land on the
primary when the replica falls more than 2 s behind and is taken out of the pool. Every
statement slows down as the load grows; a copy also locks the rows it copies until it
commits, and the replica must apply every row it changes.

Incidents are **migration windows**, at random like releases in production; each renames
another column (email → email_address, phone → phone_number, ...). Some bring trouble: the
deploy is **rolled back halfway** (a canary alarm, an error spike elsewhere) and later rolled
forward, the **replica lags** (a long analytics query, a saturated disk), or the **database
gets busy** (a traffic peak, the nightly billing job). The first window is always at 0:20,
with a rollback. The run never restarts: the table, the fleet and the clock carry on.

```
uv run python -m live zero_downtime_migration            # watch it; edit main.py and save
uv run python -m live zero_downtime_migration --lesson   # the concept, links and a checklist
uv run pytest labs/zero_downtime_migration               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see (first window, 12 seeds) |
|---|---|---|
| 0 Rename in place (given) | `migrate` renames the column at once; the new code uses only the new name | every old instance fails until it is replaced, and again after the rollback: 1,003–1,352 errors |
| 1 Expand/contract | add the column, write both (`m.write_old`), read the old one (`m.read_new`), one `db.copy` of every row, switch and drop after `fleet.released()` | no errors, but the copy locks every row for 7.5 s (write p99 6.5–7.1 s), and 102–177 names written by old instances during the rollback are wrong |
| 2 Throttled, verified backfill | `backfill`: BATCH rows a copy, PAUSE between them, wait while `busy()`; `verify` re-copies the batches that differ | no errors, write p99 25–29 ms, no wrong names, done in 42–49 s |

Without `verify` the batches still leave 21–54 wrong names after the rollback; without
`busy()` the copies run on while restarted instances warm up, and write p99 reaches 64–102 ms
(and far more when the replica lags or the database is busy).

Goals, judged per window: errors = 0 (requests that failed, during); write p99 < 40 ms (writes
started during the window); wrong names = 0 (reads that returned a name other than the latest,
plus the rows left with a wrong name in the column the app reads at the end; after); done in
≤ 60 s (the old column dropped, the new one there; after).

**Lanes picture** (the default). Users wait for their name (orange once a write takes longer
than 40 ms). The door is the app fleet: orange while old and new instances run side by side,
shut in red while requests fail on a column that is gone. Answers fade at the door: green, red
(failed), deep orange (a wrong name). The server is the database: its gauge is the load (orange
above 60%, red above 72%), its outline purple while the backfill copies. Under it: which columns
hold the name, and how much is copied. The chart is the load, second by second: the app (white),
other work (orange) and your copies (purple), with the line where write p99 passes 40 ms; copies
and trouble are shaded.

**Cluster picture.** Press `v` (or `--view cluster`): the six instances on top (white old
release, blue new, dim while they restart, red while they fail), and below them the migration
runner, the primary and its replica. Requests fly to an instance and on to the primary, coloured
by the columns they touch (white old, blue new, light orange both: a dual write); failures die
in red. Purple dots fly from the runner while it copies; orange ones to the replica while it lags.

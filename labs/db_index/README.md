# Lab: database index

*[Leer en español](es/README.md)*

A `users` table starts with 20,000 rows and keeps growing: ~5 signups/s, and now and then a
bulk import. Users log in (`find_by_email`, ~30/s) and dashboards ask who signed up in a
country in a time range (`signups_between`, ~2/s). The database has 4 workers; each query
costs 0.2 ms plus 5 µs per row it reads, and a user gives up after waiting 2 s for a worker.
Every answer is checked: a wrong one is a failed query.

Incidents come at random, like in production: a bulk import (10,000–20,000 rows with old
signup times, in a few seconds), a new report that runs many large range queries, or a
spike of logins. The run never restarts, so the table only grows. The first incident is
always an import at 0:20.

```
uv run python -m live db_index          # watch it; edit main.py and save
uv run python -m live db_index --lesson # the concept, links and a checklist
uv run pytest labs/db_index             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Full scans (given) | every query scans the table | a login reads ~20k rows and takes ~0.1 s; the first import pushes p99 past 1 s and later ones make users give up |
| 1 Hash index | a dict email -> position for `find_by_email` | a login reads 1 row, but a range still reads ~900x the rows it returns (p99 ~200 ms) |
| 2 Hash + composite index | per country, a sorted list of (time, position); bisect in `signups_between` | every query reads only what it returns (1.0x); p99 under 1 ms; every goal OK |

Goals, judged per incident: rows read per login ≤ 5 (the 15 s before), rows read per row a
range returns ≤ 2x (the 15 s before), p99 latency < 100 ms and ≥ 99% answered (queries
started during the incident; a user who gave up counts as failed).

- The stage is judged from the **rows read**, not from the latency: a full scan is fast on a
  small table, and gets slower every day as the table grows.
- Imports insert rows with **old times**, so the composite index must stay sorted: use
  `insort`, not `append`.
- The chart is database busy time as a % of the 4 workers, coloured by how many rows each
  query read: white a few, orange hundreds to thousands, dark orange a full scan.

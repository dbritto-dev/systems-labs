# Lab: cache stampede

*[Leer en español](es/README.md)*

Users open ~200 pages/s; each page reads 3 keys through your `get()`. Popularity is
Zipf-skewed (a few hot keys), and the 5 hottest keys are expensive aggregates that
take 8x longer to build. The database takes 20 ms per read and does 8 reads at a
time (~400 reads/s); beyond that reads queue, and a full queue rejects reads.

The incident is a **cache flush**: at random times, like in production, a deploy,
an out-of-memory restart or a failover to a cold replica empties the cache. The
first one is always at 0:20. The run never restarts, so the cache refills (or
stampedes) on its own.

```
uv run python -m live caching            # watch it; edit main.py and save
uv run python -m live caching --lesson   # the concept, links and a checklist
uv run pytest labs/caching               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 (given) | every read goes to the database | 600 reads/s against a 400/s database: `OVERLOADED` |
| 1 | cache-aside with a TTL | ~90% hits; each flush sets off deep-orange duplicate loads |
| 2 | single-flight loads + jittered TTLs | one load per key after a flush; every goal OK |

Goals, judged per flush: hit ratio ≥ 80% (15 s before), duplicate loads < 5% of
database reads (first 5 s), p99 read time < 100 ms (reads started in the 10 s after).

**Pictures:** `lanes` (the default) and `cluster`: clients → the app, which asks the cache (right) and reads the database (below) on a miss; the cache turns orange while it is empty. Press `v` to switch, or start with `--view cluster`.

# Lab: cache stampede

Users open ~200 pages/s; each page reads 3 keys through your `get()`. Popularity is
Zipf-skewed (a few hot keys), and the 5 hottest keys are expensive aggregates that
take 8x longer to build. The database takes 20 ms per read and does 8 reads at a
time (~400 reads/s); beyond that reads queue, and a full queue rejects reads.

The incident is a **cache flush**: at random times, like in production, a deploy,
an out-of-memory restart or a failover to a cold replica empties the cache. The
first one is always at 0:20. The run never restarts, so the cache refills (or
stampedes) on its own.

```
uv run python -m live cache            # watch it; edit main.py and save
uv run python -m live cache --lesson   # the concept, links and a checklist
uv run pytest labs/cache               # x = not yet, X = done
```

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 (given) | every read goes to the database | 600 reads/s against a 400/s database: `OVERLOADED` |
| 1 | cache-aside with a TTL | ~90% hits; each flush sets off deep-orange duplicate loads |
| 2 | single-flight loads + jittered TTLs | one load per key after a flush; every goal OK |

Goals, judged per flush: hit ratio ≥ 80% (15 s before), duplicate loads < 5% of
database reads (first 5 s), p99 read time < 100 ms (reads started in the 10 s after).

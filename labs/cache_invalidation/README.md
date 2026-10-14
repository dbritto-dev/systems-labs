# Lab: cache invalidation

*[Leer en español](es/README.md)*

Users open ~300 product pages a second through three app servers, each with its own
`ProductCache` over one shared cache (like memcached) and one database. Popularity is skewed: a
few products get most of the views. Writes come from checkouts (~5/s, the stock), admins and
import jobs, through `update(key, record)`. Every app server stops now and then for a
garbage-collection pause (30–150 ms), the product query runs 8–25 ms after it took its snapshot,
and a few replies are much slower: a reader can store what it loaded long after it loaded it.
At random times, like in production, a price campaign rewrites the popular products' prices
(two writes per product, a few ms apart; some hit lock timeouts), an import rewrites the whole
catalogue (some rows break a constraint), the network gets slow (every race window widens), or
the cache node restarts (it answers nothing for 1–4 s and comes back empty). The run never
restarts. The first incident is always a price campaign at 0:20–0:30. The `caching` lab is about
load (stampedes, TTLs); this one is about correctness while the data changes.

```
uv run python -m live cache_invalidation          # watch it; edit main.py and save
uv run python -m live cache_invalidation --lesson # the concept, links and a checklist
uv run pytest labs/cache_invalidation             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see in the first campaign |
|---|---|---|
| 0 Cache, then database (given) | `update`: `cache.set`, then `db.write`; `read`: get, else read and set | 110–230 reads served a price the database refused (red at the door), 20–35 stale reads, ~10 stale keys |
| 1 Write, then delete | `update`: `db.write`, then `cache.delete` | nothing unsaved, but slow fills put old prices back after the delete (red fills in the cluster picture): 6–85 stale reads, 2–3 stale keys that stay for the TTL (5 min) |
| 2 Leased fills | `read`: `lease_get`, and on a miss `lease_set(key, record, token, TTL)`; `TTL = 30` | the same late fills are refused (orange): 0 stale reads, 0 stale keys, hit ratio ~90%, ~90 DB reads/s at most; every goal OK |

Goals, judged per incident: hit ratio ≥ 85% (the 15 s before), reads that served a price that was
never saved = 0 and stale reads = 0 (a read is stale when it started more than 0.5 s after a write
was acknowledged and returned something older, for reads started during the incident), stale keys
in the cache = 0 (checked every second, during the incident and 5 s after) and DB reads ≤ 500/s.

Two pictures: `lanes` (opens first) shows users' reads flying to the cache (the door: white a hit,
orange a miss that goes on to the database, the server), writes in blue, and what came back: green
fresh, red stale or never saved; the door turns red while the cache holds stale keys. `cluster`
shows the three app servers (orange during a GC pause), the cache and the database: fills after a
miss are white, red when the record is already older than the database's (a stale fill), orange
when the cache refuses one; press `v` to switch.

- **Why delete, not set.** Two writers that set the cache after the database can arrive in the
  other order: the cache ends with the older price (`WRITE_SET` in the tests). A delete has no
  value to get wrong.
- **Why the database first.** Delete first and a reader can miss, load the old row and refill it
  before your write commits (`DELETE_FIRST`). With leases too: the reader takes its lease after
  your delete, so nothing invalidates it (`LEASE_DELETE_FIRST`).
- **Why leases.** The reader's fill is the problem: it carries data from before the write and
  lands after the delete. A lease ties the fill to the miss; a delete in between voids it.
- **Why not a tiny TTL instead.** A 0.2 s TTL hides most stale keys, and the hit ratio falls to
  ~35% (`TINY_TTL`): all those reads go to the database.

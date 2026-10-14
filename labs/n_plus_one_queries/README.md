# Lab: N+1 queries

*[Leer en español](es/README.md)*

Users open ~30 pages/s. A page lists the orders of one shop (10–30, many more during a
sale) and shows each order's customer. Your `load_page(page_id, db)` builds it from a
database that runs 8 queries at a time, ~2 ms a round trip plus a little per row. At random,
like in production, the database gets slower per round trip (a backup, a noisy disk, a
failover), pages get much longer (a sale), or traffic spikes. The first incident is always
a slow database at 0:20–0:30.

```
uv run python -m live n_plus_one_queries            # watch it; edit main.py and save
uv run python -m live n_plus_one_queries --lesson   # the concept, links and a checklist
uv run pytest labs/n_plus_one_queries               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 N+1 (given) | one `fetch_customer` per order | ~21 queries per page; a slow database saturates its 8 connections and pages time out |
| 1 Batched | one `fetch_customers(ids)` (IN) per page | 2 queries per page, the database nearly idle; but 2 slow round trips: p99 ~45 ms |
| 2 Joined | one `fetch_orders_with_customers` (JOIN) per page | 1 query per page: one round trip even when it is slow (p99 ~25 ms) |

Goals, judged per incident: baseline ok and queries per page ≤ 2 (in the 15 s before it),
database busy < 90% and p99 page time < 40 ms (during), pages served ≥ 99% (after).
Running the N queries concurrently (`asyncio.gather`) stays at stage 0: it is just as many
queries.

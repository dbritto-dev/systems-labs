"""Lab n_plus_one_queries: YOUR FILE. Edit it and save; the live window reruns it.

Users open ~30 pages/s. Each page lists the orders of one shop (10-30 of them, many more
during a sale) and shows each order's customer. `load_page` builds a page from the
database. Right now it asks for the orders, then asks for each customer one by one: one
query for the list plus one per order. That is the N+1 query problem.

Every query is a round trip (~2 ms, much more when the database is slow) and the
database runs only 8 at a time. Do the stages in order, in this file:

  Stage 1  Batch: get all the customers of the page in ONE query
           (`db.fetch_customers(ids)`, a WHERE id IN (...)): 2 queries per page.
  Stage 2  Join: get the orders and their customers in ONE query
           (`db.fetch_orders_with_customers(page_id)`): 1 query per page, so one round
           trip even when each round trip is slow.

The database (all async, each call is one query):
  await db.fetch_orders(page_id)                -> [{"id", "customer_id"}, ...]
  await db.fetch_customer(customer_id)          -> {"id", "name"}
  await db.fetch_customers(customer_ids)        -> {customer_id: {"id", "name"}}
  await db.fetch_orders_with_customers(page_id) -> [(order, customer), ...]

Check yourself:  uv run pytest labs/n_plus_one_queries
Peek at a solution (after trying!):  labs/n_plus_one_queries/reference.py
"""

from __future__ import annotations


async def load_page(page_id: int, db) -> list[dict]:
    """Return one row per order of the page: {"order": order, "customer": its customer}.

    Contract: every order of the page, each with its own customer (the checker
    compares). The order of the rows does not matter.
    """
    # Stage 1: instead of one fetch_customer per order, collect the customer ids and
    # call db.fetch_customers(ids) once; then build the rows from the dict it returns.
    # Stage 2: one call, db.fetch_orders_with_customers(page_id), gives (order, customer)
    # pairs directly.
    orders = await db.fetch_orders(page_id)
    rows = []
    for order in orders:
        customer = await db.fetch_customer(order["customer_id"])  # one query per order: N+1
        rows.append({"order": order, "customer": customer})
    return rows

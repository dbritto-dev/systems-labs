"""Lab n_plus_one: a working solution. Read it after you have tried main.py."""

from __future__ import annotations


async def load_page(page_id: int, db) -> list[dict]:
    # One query, one round trip: the database joins orders and customers for us.
    return [{"order": order, "customer": customer}
            for order, customer in await db.fetch_orders_with_customers(page_id)]

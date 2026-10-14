"""Laboratorio n_plus_one_queries: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations


async def load_page(page_id: int, db) -> list[dict]:
    # Una consulta, un viaje: la base de datos junta pedidos y clientes por nosotros.
    return [{"order": order, "customer": customer}
            for order, customer in await db.fetch_orders_with_customers(page_id)]

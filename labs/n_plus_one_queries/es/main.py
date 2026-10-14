"""Laboratorio n_plus_one_queries: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los usuarios abren ~30 páginas/s. Cada página lista los pedidos de una tienda (de 10 a 30,
muchos más en unas rebajas) y muestra el cliente de cada pedido. `load_page` construye una
página desde la base de datos. Ahora mismo pide los pedidos y luego cada cliente uno a uno:
una consulta para la lista más una por pedido. Ese es el problema de las consultas N+1.

Cada consulta es un viaje de ida y vuelta (~2 ms, mucho más cuando la base de datos va
lenta) y la base de datos solo ejecuta 8 a la vez. Haz las etapas en orden, en este archivo:

  Etapa 1  Agrupar: trae todos los clientes de la página en UNA consulta
           (`db.fetch_customers(ids)`, un WHERE id IN (...)): 2 consultas por página.
  Etapa 2  Unir: trae los pedidos y sus clientes en UNA consulta
           (`db.fetch_orders_with_customers(page_id)`): 1 consulta por página, así que un
           solo viaje aunque cada viaje sea lento.

La base de datos (todo async; cada llamada es una consulta):
  await db.fetch_orders(page_id)                -> [{"id", "customer_id"}, ...]
  await db.fetch_customer(customer_id)          -> {"id", "name"}
  await db.fetch_customers(customer_ids)        -> {customer_id: {"id", "name"}}
  await db.fetch_orders_with_customers(page_id) -> [(pedido, cliente), ...]

Compruébalo:  LABS_LANG=es uv run pytest labs/n_plus_one_queries
Mira una solución (¡después de intentarlo!):  labs/n_plus_one_queries/es/reference.py
"""

from __future__ import annotations


async def load_page(page_id: int, db) -> list[dict]:
    """Devuelve una fila por pedido de la página: {"order": pedido, "customer": su cliente}.

    Contrato: todos los pedidos de la página, cada uno con su propio cliente (el comprobador
    lo compara). El orden de las filas no importa.
    """
    # Etapa 1: en vez de un fetch_customer por pedido, junta los ids de cliente y llama una
    # vez a db.fetch_customers(ids); luego construye las filas con el dict que devuelve.
    # Etapa 2: una sola llamada, db.fetch_orders_with_customers(page_id), da directamente
    # las parejas (pedido, cliente).
    orders = await db.fetch_orders(page_id)
    rows = []
    for order in orders:
        customer = await db.fetch_customer(order["customer_id"])  # una consulta por pedido: N+1
        rows.append({"order": order, "customer": customer})
    return rows

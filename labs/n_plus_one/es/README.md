# Laboratorio: consultas N+1

*[Read in English](../README.md)*

Los usuarios abren ~30 páginas/s. Una página lista los pedidos de una tienda (de 10 a 30,
muchos más en unas rebajas) y muestra el cliente de cada pedido. Tu `load_page(page_id, db)`
la construye desde una base de datos que ejecuta 8 consultas a la vez, ~2 ms por viaje más
un poco por fila. Al azar, como en producción, la base de datos va más lenta en cada viaje
(una copia de seguridad, un disco ruidoso, un cambio de zona), las páginas se alargan mucho
(unas rebajas) o hay un pico de tráfico. El primer incidente siempre es una base de datos
lenta entre 0:20 y 0:30.

```
uv run python -m live n_plus_one --lang es            # míralo; edita es/main.py y guarda
uv run python -m live n_plus_one --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/n_plus_one            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 N+1 (dada) | un `fetch_customer` por pedido | ~21 consultas por página; con la BD lenta se llenan sus 8 conexiones y las páginas dan timeout |
| 1 Agrupadas | un `fetch_customers(ids)` (IN) por página | 2 consultas por página y la BD casi parada; pero 2 viajes lentos: p99 ~45 ms |
| 2 Con JOIN | un `fetch_orders_with_customers` (JOIN) por página | 1 consulta por página: un solo viaje aunque sea lento (p99 ~25 ms) |

Objetivos, evaluados en cada incidente: base correcta y consultas por página ≤ 2 (en los
15 s anteriores), BD ocupada < 90% y p99 de página < 40 ms (durante), páginas servidas ≥ 99%
(después). Lanzar las N consultas a la vez (`asyncio.gather`) se queda en la etapa 0: son las
mismas consultas.

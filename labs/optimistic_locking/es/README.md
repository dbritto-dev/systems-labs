# Laboratorio: bloqueo optimista

*[Read in English](../README.md)*

Los usuarios compran ~50 veces por segundo a través de tres servidores de aplicación, cada uno
con su propio `StockService.adjust(item, delta)` sobre una misma tabla de inventario. Cada
petición es un leer-modificar-escribir: lee la fila, suma `delta` (una venta quita 1–3
unidades) y escribe el valor nuevo. Un usuario espera hasta 1 s; un 409 (`Conflict`) es una
página de error. En momentos al azar, como en producción, una oferta relámpago manda casi todo
de 2–3,5 veces el tráfico a un solo artículo (una notificación, un error de precio), una carga
masiva repone los artículos populares mientras los usuarios los compran (el inventario de un
proveedor, una sincronización nocturna), o la red hasta la base de datos se vuelve lenta (un
cambio de zona, pérdida de paquetes: crece el hueco entre la lectura y la escritura de cada
petición). La ejecución nunca se reinicia. El primer incidente es siempre una oferta relámpago a
los 0:20–0:30.

```
LABS_LANG=es uv run python -m live optimistic_locking          # míralo; edita es/main.py y guarda
LABS_LANG=es uv run python -m live optimistic_locking --lesson # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/optimistic_locking             # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Gana la última escritura (dada) | `read`, suma `delta`, `write` | cada petición se atiende en ~6 ms, y la oferta pierde ~250 cambios (rojo): el inventario queda mal y nadie lo sabe |
| 1 Control de versión | `compare_and_set(item, new, row.version)`; lanza `Conflict` si no coincide con ninguna fila | no se pierde nada, pero ~13% de las peticiones de una oferta reciben un 409 (naranja) |
| 2 Reintento y combinación | tras un conflicto, espera `backoff(attempt, rng)` (jitter completo, con tope), vuelve a leer y aplica `delta` otra vez, hasta `MAX_TRIES` | nada perdido, 409 ~0%, p99 ~50 ms en una oferta (~250 ms con la base de datos lenta); todos los objetivos OK |

Objetivos, juzgados por incidente: base correcta (peticiones atendidas antes), cambios
perdidos = 0, 409 ≤ 1%, p99 < 500 ms y atendidas ≥ 98% (todo para las peticiones que empiezan
durante el incidente).

Dos dibujos: `lanes` (se abre primero) muestra a los usuarios enviando escrituras (blanco,
naranja más intenso en cada reintento) a la API, y lo que vuelve a la puerta: atendida en verde,
409 en naranja, un cambio que borró otros en rojo. `cluster` muestra los tres servidores y la
base de datos: escrituras que se consolidan en blanco, las que fallan el control de versión en
naranja, las que borran otras en rojo; pulsa `v` para cambiar.

- **Por qué no basta un bloqueo en tu código.** Un `asyncio.Lock` por artículo funciona dentro de
  un servidor; los otros dos tienen el suyo, y siguen escribiendo unos encima de otros. La
  comprobación tiene que hacerse en la base de datos, en la misma sentencia que la escritura.
- **Por qué volver a leer.** Reintentar el mismo `compare_and_set` con la versión que leíste al
  principio no puede ganar nunca: la fila ya ha cambiado. Vuelve a leer y aplica tu cambio a lo
  que hay ahora.
- **Por qué jitter y tope.** Las peticiones que perdieron una carrera la perdieron juntas; sin
  jitter vuelven juntas y chocan otra vez. Sin tope, unas pocas peticiones con mala suerte
  esperan segundos (`0.1 * 2 ** attempt` falla el objetivo de p99).

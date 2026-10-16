# Laboratorio: invalidación de caché

*[Read in English](../README.md)*

Los usuarios abren ~300 fichas de producto por segundo a través de tres servidores de aplicación,
cada uno con su propio `ProductCache` sobre una caché compartida (como memcached) y una base de
datos. La popularidad está sesgada: unos pocos productos reciben casi todas las visitas. Las
escrituras llegan de las compras (~5/s, el inventario), de los administradores y de los procesos
de carga, mediante `update(key, record)`. Cada servidor se detiene de vez en cuando por una pausa
del recolector de basura (30–150 ms), la consulta de producto tarda 8–25 ms después de tomar su
instantánea, y algunas respuestas son mucho más lentas: un lector puede guardar lo que cargó mucho
después de cargarlo. En momentos al azar, como en producción, una campaña de precios reescribe los
precios de los productos populares (dos escrituras por producto, a pocos ms; algunas dan timeout
de bloqueo), una carga reescribe todo el catálogo (algunas filas incumplen una restricción), la red
se vuelve lenta (crece cada hueco para colarse), o el nodo de caché se reinicia (no responde
durante 1–4 s y vuelve vacío). La ejecución nunca se reinicia. El primer incidente es siempre una
campaña de precios a los 0:20–0:30. El laboratorio `caching` trata de la carga (estampidas, TTL);
este trata de la corrección mientras los datos cambian.

```
LABS_LANG=es uv run python -m live cache_invalidation          # míralo; edita es/main.py y guarda
LABS_LANG=es uv run python -m live cache_invalidation --lesson # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/cache_invalidation             # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves en la primera campaña |
|---|---|---|
| 0 Caché, luego base de datos (dada) | `update`: `cache.set` y luego `db.write`; `read`: get, si no lee y hace set | 110–230 lecturas sirvieron un precio que la base de datos rechazó (rojo en la puerta), 20–35 lecturas viejas, ~10 claves viejas |
| 1 Escribir y luego borrar | `update`: `db.write` y luego `cache.delete` | nada sin guardar, pero los rellenos lentos reponen precios viejos tras el borrado (rellenos rojos en el dibujo del clúster): 6–85 lecturas viejas, 2–3 claves viejas que duran todo el TTL (5 min) |
| 2 Rellenos con concesión | `read`: `lease_get` y, al fallar, `lease_set(key, record, token, TTL)`; `TTL = 30` | esos mismos rellenos tardíos se rechazan (naranja): 0 lecturas viejas, 0 claves viejas, ~90% de aciertos, ~90 lecturas de BD/s como mucho; todos los objetivos OK |

Objetivos, evaluados por incidente: aciertos ≥ 85% (los 15 s anteriores), lecturas que sirvieron un
precio que nunca se guardó = 0 y lecturas viejas = 0 (una lectura es vieja si empezó más de 0.5 s
después de confirmar al cliente una escritura y devolvió algo más antiguo; para las lecturas que
empiezan durante el incidente), claves viejas en la caché = 0 (se mira cada segundo, durante el
incidente y 5 s después) y lecturas de la BD ≤ 500/s.

Dos dibujos: `lanes` (se abre primero) muestra las lecturas de los usuarios volando hacia la caché
(la puerta: blanco un acierto, naranja un fallo que sigue hasta la base de datos, el servidor), las
escrituras en azul, y lo que volvió: verde al día, rojo viejo o nunca guardado; la puerta se pone
roja mientras la caché guarda claves viejas. `cluster` muestra los tres servidores (naranjas
durante una pausa), la caché y la base de datos: los rellenos tras un fallo son blancos, rojos si el
registro ya es más viejo que el de la base de datos (un relleno viejo), naranjas si la caché lo
rechaza; pulsa `v` para cambiar.

- **Por qué borrar y no actualizar.** Dos escrituras que actualizan la caché después de la base de
  datos pueden llegar en el otro orden: la caché acaba con el precio más viejo (`WRITE_SET` en los
  tests). Un borrado no lleva ningún valor que pueda estar mal.
- **Por qué primero la base de datos.** Si borras primero, un lector puede fallar, cargar la fila
  vieja y reponerla antes de que tu escritura se consolide (`DELETE_FIRST`). También con
  concesiones: el lector toma la suya después de tu borrado, y nada la anula (`LEASE_DELETE_FIRST`).
- **Por qué concesiones.** El problema es el relleno del lector: lleva datos de antes de la
  escritura y llega después del borrado. Una concesión ata el relleno al fallo; un borrado entre
  medias la anula.
- **Por qué no un TTL minúsculo.** Un TTL de 0.2 s oculta casi todas las claves viejas, y los
  aciertos caen a ~35% (`TINY_TTL`): todas esas lecturas van a la base de datos.

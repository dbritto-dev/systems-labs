# Laboratorio: estampida en la cache

*[Read in English](../README.md)*

Los usuarios abren ~200 páginas/s; cada página lee 3 claves con tu `get()`. La popularidad
sigue una Zipf (unas pocas claves calientes), y las 5 claves más calientes son agregados
caros que tardan 8 veces más en construirse. La base de datos tarda 20 ms por lectura y
hace 8 a la vez (~400 lecturas/s); por encima de eso las lecturas hacen cola, y una cola
llena rechaza lecturas.

El incidente es un **vaciado de la cache**: en momentos al azar, como en producción, un
despliegue, un reinicio por falta de memoria o una conmutación a una réplica fría dejan la
cache vacía. El primero siempre es a las 0:20. La ejecución nunca se reinicia, así que la
cache se vuelve a llenar (o provoca una estampida) por sí sola.

```
uv run python -m live cache --lang es            # míralo; edita es/main.py y guarda
uv run python -m live cache --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/cache            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 (dada) | cada lectura va a la base de datos | 600 lecturas/s contra una base de datos de 400/s: `SATURADO` |
| 1 | cache-aside con un TTL | ~90% de aciertos; cada vaciado provoca cargas duplicadas naranja oscuro |
| 2 | cargas single-flight + TTL con jitter | una carga por clave tras un vaciado; todos los objetivos OK |

Objetivos, evaluados en cada vaciado: aciertos ≥ 80% (15 s antes), cargas duplicadas < 5%
de las lecturas de la base de datos (primeros 5 s), p99 del tiempo de lectura < 100 ms
(lecturas empezadas en los 10 s siguientes).

**Dibujos:** `lanes` (carriles, el de siempre) y `cluster`: clientes → la app, que pregunta a la cache (derecha) y lee la base de datos (abajo) si falla; la cache se pone naranja mientras está vacía. Pulsa `v` para cambiar, o empieza con `--view cluster`.

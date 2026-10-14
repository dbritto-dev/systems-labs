# Laboratorio: contador solo creciente (Gossip Glomers n.º 4 de Fly.io)

*[Read in English](../README.md)*

El reto n.º 4 de [Gossip Glomers](https://fly.io/dist-sys/4/), en Python, sobre una red
simulada: 3 nodos sin estado en una LAN (20 ms por mensaje) y el servicio `seq-kv` de
Maelstrom, un almacén clave/valor *secuencialmente consistente*: una lectura puede devolver un
valor de hasta 0.5 s de antigüedad, aunque nunca más viejo que tus propias escrituras. Los
clientes envían `add` (un delta) y `read` (el total).

Los incidentes llegan al azar, como en producción: picos de sumas (una venta relámpago, un cliente
atascado en un bucle de reintentos) y una red lenta. El primero siempre es un pico de 3x entre
0:20 y 0:30.

```
uv run python -m live grow_only_counter --lang es            # míralo; edita es/main.py y guarda
uv run python -m live grow_only_counter --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/grow_only_counter            # x = aún no, X = hecho
```

Dos dibujos: `cluster` (el de siempre: los nodos y los mensajes entre ellos) y `lanes`
(lo que ven los clientes: sus peticiones esperando, la red como una puerta, el clúster como
un solo servidor). Pulsa `v` para cambiar, o empieza con `--view lanes`.

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 En memoria (dada) | cada nodo cuenta sus propias sumas | seq-kv no recibe nada; cada lectura se queda corta |
| 1 Clave compartida | lee `counter`, suma y escríbela de vuelta | los nodos se pisan: las lecturas pierden sumas confirmadas |
| 2 Compare-and-swap | `cas` y reintenta con el código 22 | no se pierde nada, pero chocan el 80-99% de los CAS; en un pico las sumas dan timeout |
| 3 Clave por nodo | cada nodo escribe solo su propia clave; una lectura las suma | sin conflictos; todas las lecturas cuadran |

Objetivos, evaluados en cada incidente: la cuenta vive en seq-kv (antes), sin sumas perdidas
(antes), conflictos < 10% de los compare-and-swap (durante), sumas respondidas ≥ 99%
(durante), lecturas correctas otra vez 2-7 s después (después).

Una lectura es *correcta* cuando su valor es al menos todas las sumas confirmadas 1.5 s antes
de que empezara la lectura (seq-kv puede ir 0.5 s atrasado) y como mucho todas las sumas
enviadas antes de que terminara. En el dibujo seq-kv es el nodo morado; los conflictos
parpadean en rojo al volver de él.

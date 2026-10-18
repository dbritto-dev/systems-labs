# Laboratorio: log de Kafka (Gossip Glomers #5 de Fly.io)

*[Read in English](../README.md)*

El reto #5 de [Gossip Glomers](https://fly.io/dist-sys/), en Python, sobre una red simulada:
dos nodos y el `lin-kv` de Maelstrom, ~10 ms por mensaje. Los clientes (~30 operaciones/s)
hablan con cualquiera de los dos nodos: `send` añade un mensaje al log de una clave y recibe su
offset, `poll` lee desde un offset, y `commit_offsets` y `list_committed_offsets` registran hasta
dónde llegaron los consumidores.

Los incidentes llegan al azar, como en producción: una avalancha de sends a una clave caliente
(2-2.5x el tráfico), o lin-kv que se vuelve 2-4x más lento. El primero siempre es una avalancha
entre 0:20 y 0:30.

```
uv run python -m live kafka_style_log --lang es            # míralo; edita es/main.py y guarda
uv run python -m live kafka_style_log --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/kafka_style_log            # x = aún no, X = hecho
```

Dos dibujos: `cluster` (el de siempre: los nodos y los mensajes entre ellos) y `lanes`
(lo que ven los clientes: sus peticiones esperando, la red como una puerta, el clúster como
un solo servidor). Pulsa `v` para cambiar, o empieza con `--view lanes`.

| Etapa | Reto | En `es/main.py` | Lo que ves |
|---|---|---|---|
| 0 Un solo nodo (dada) | 5a | cada nodo guarda su propio log | offsets duplicados, escrituras perdidas, commits perdidos |
| 1 Multinodo | 5b | offsets y mensajes en lin-kv (un contador CAS por clave) | sin anomalías, pero ~10 msgs/op y p99 de send de 300-700 ms en una avalancha |
| 2 Eficiente | 5c | menos viajes de ida y vuelta (p. ej. un nodo dueño por clave) | ~1.3 msgs/op, p99 de send ~47 ms, incluso en avalanchas |

Objetivos, evaluados en cada incidente: offsets únicos y crecientes (15 s antes; un send nunca
recibe un offset menor que uno ya confirmado, un poll los da en orden), ninguna escritura perdida
(durante), offsets con commit conservados (10 s después), mensajes por operación < 3 (antes;
entre los nodos y lin-kv, divididos por las operaciones de los clientes), y p99 de send < 100 ms
(durante).

El comprobador mira cada respuesta, como el comprobador kafka de Maelstrom: dos sends confirmados
con el mismo offset para una clave; un poll que devuelve un offset pero se salta uno anterior ya
confirmado (o devuelve otro mensaje en él); un offset con commit listado por debajo de un commit
confirmado.

# Laboratorio: log de Kafka (Gossip Glomers #5 de Fly.io)

*[Read in English](../README.md)*

El reto #5 de [Gossip Glomers](https://fly.io/dist-sys/), en Python, sobre una red simulada:
dos nodos y los dos almacenes de Maelstrom, `lin-kv` (linealizable) y `seq-kv` (secuencialmente
consistente: una lectura puede tener hasta 0,5 s de antigüedad), ~10 ms por mensaje. Los clientes (~30 operaciones/s)
hablan con cualquiera de los dos nodos: `send` añade un mensaje al log de una clave y recibe su
offset, `poll` lee desde un offset, y `commit_offsets` y `list_committed_offsets` registran hasta
dónde llegaron los consumidores.

Los incidentes llegan al azar, como en producción: una avalancha de sends a una clave caliente
(2-2.5x el tráfico), o el almacén (lin-kv y seq-kv) que se vuelve 2-4x más lento. El primero siempre es una avalancha
entre 0:20 y 0:30.

```
uv run python -m live kafka_style_log --lang es            # míralo; edita es/main.py y guarda
uv run python -m live kafka_style_log --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/kafka_style_log            # x = aún no, X = hecho
```

Tres dibujos: `fanin` (el de siempre: los sends, polls y commits llegan por la red a los nodos n0
y n1, cada indicador sus operaciones de cliente por segundo; un nodo destella del color de su
anomalía: naranja un offset duplicado, amarillo un offset que retrocede, rojo una escritura
perdida, rosa un commit perdido; los nodos guardan el log en el almacén (lin-kv o seq-kv, una sola caja), morado, naranja mientras va
lento, su indicador sus mensajes por segundo; esos mensajes vuelan en naranja claro, y una petición
que un nodo pasa al dueño de la clave vuela en azul entre los nodos), `cluster` (los mismos nodos y
colores, y los mensajes entre ellos) y `lanes` (lo que ven los clientes: sus peticiones esperando,
la red como una puerta, el clúster como un solo servidor). Pulsa `v` para cambiar, o empieza con
`--view lanes`.

| Etapa | Reto | En `es/main.py` | Lo que ves |
|---|---|---|---|
| 0 Nada aún (dada) | | sin handlers: cada petición recibe un error | errores por todas partes, nada respondido |
| 1 Un solo nodo | 5a | cada nodo guarda su propio log | offsets duplicados, escrituras perdidas, commits perdidos |
| 2 Multinodo | 5b | offsets y mensajes en lin-kv o seq-kv (un contador CAS por clave), commits en lin-kv | sin anomalías, pero ~10 msgs/op y p99 de send de 300-700 ms en una avalancha |
| 3 Eficiente | 5c | menos viajes de ida y vuelta (p. ej. un nodo dueño por clave) | ~1.3 msgs/op, p99 de send ~47 ms, incluso en avalanchas |

Qué almacén para qué (Fly.io 5b te pide elegir): un mensaje guardado una vez bajo su propia clave
nunca cambia, así que una lectura vieja de seq-kv no puede mostrar otro anterior; y un contador con
CAS se compara con el último valor, así que en seq-kv una lectura vieja solo cuesta un CAS fallido y
un reintento. Los dos pueden ir en seq-kv. Los commits no: el otro nodo puede leer un commit
anterior, y un commit listado por debajo de uno confirmado es un commit perdido. Guárdalos en
lin-kv. (La referencia no usa ningún almacén: cada clave tiene un nodo dueño que guarda su log en
memoria.)

Objetivos, evaluados en cada incidente: operaciones de clientes respondidas ≥ 99% (15 s antes),
offsets únicos y crecientes (también antes; un send nunca recibe un offset menor que uno ya
confirmado, un poll los da en orden), ninguna escritura perdida (durante), offsets con commit
conservados (10 s después), mensajes por operación < 3 (antes; entre los nodos y el almacén,
divididos por las operaciones de los clientes), y p99 de send < 100 ms (durante).

El comprobador mira cada respuesta, como el comprobador kafka de Maelstrom: dos sends confirmados
con el mismo offset para una clave; un poll que devuelve un offset pero se salta uno anterior ya
confirmado (o devuelve otro mensaje en él); un offset con commit listado por debajo de un commit
confirmado.

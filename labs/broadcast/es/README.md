# Laboratorio: broadcast (Gossip Glomers #3 de Fly.io)

*[Read in English](../README.md)*

El reto #3 de [Gossip Glomers](https://fly.io/dist-sys/), en Python, sobre una red simulada:
25 nodos, ~100 ms por mensaje. Los clientes envían a cada nodo `broadcast` (un número nuevo) y
`read` (¿qué números tienes?). Cada número tiene que llegar a cada nodo. Las particiones de red
llegan al azar, como en producción; la primera siempre parte el clúster entre 0:20 y 0:30.

```
uv run python -m live broadcast --lang es            # míralo; edita es/main.py y guarda
uv run python -m live broadcast --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/broadcast            # x = aún no, X = hecho
```

Dos dibujos: `cluster` (el de siempre: los nodos y los mensajes entre ellos) y `lanes`
(lo que ven los clientes: sus peticiones esperando, la red como una puerta, el clúster como
un solo servidor). Pulsa `v` para cambiar, o empieza con `--view lanes`.

| Etapa | Reto | En `es/main.py` | Lo que ves |
|---|---|---|---|
| 0 Un solo nodo (dada) | 3a | guarda los números que te envían | solo un nodo tiene cada número |
| 1 Varios nodos | 3b | cuéntales los números nuevos a tus vecinos | los números se extienden, pero los enviados durante una partición se pierden |
| 2 Tolerante a fallos | 3c | reenvía hasta que confirmen | aguanta las particiones, pero ~60 msgs/op y ~700 ms |
| 3 Eficiente | 3d | menos saltos (por ejemplo, directo a cada nodo) | < 30 msgs/op, p50 < 400 ms, máx < 600 ms |
| 4 Por lotes | 3e | muchos números por mensaje | < 20 msgs/op (p50 < 1 s, máx < 2 s) |

Objetivos, evaluados en cada partición: cada nodo recibe cada número (medido en la calma de
antes), los números enviados durante la partición están en todas partes 5 s después de que se
cure, mensajes por operación < 30 y < 20, y el tiempo hasta que cada nodo tiene un número
(mediana/máximo) < 400/600 ms y < 1/2 s.

Los mensajes por operación cuentan los mensajes entre nodos, divididos por las operaciones de
los clientes (lecturas incluidas), como el `msgs-per-op` de Maelstrom. El verificador mira el
`self.messages` de cada nodo cada 20 ms, fuera de la red, así que nunca añade tráfico.

Cómo habla tu nodo está en `core/net.py`: `self.reply`, `self.send`, `await self.rpc`,
`self.every`, `self.spawn`, `self.now()`, y los manejadores `on_<tipo>`.

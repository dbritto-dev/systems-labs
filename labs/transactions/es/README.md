# Laboratorio: transacciones (Gossip Glomers n.º 6 de Fly.io)

*[Read in English](../README.md)*

El reto n.º 6 de [Gossip Glomers](https://fly.io/dist-sys/) (transacciones siempre
disponibles), en Python, sobre una red simulada: 3 nodos, ~100 ms por mensaje. Los clientes
envían a cualquier nodo una `txn`, una lista de microoperaciones (`["r", key, null]`,
`["w", key, value]`); el nodo responde `txn_ok` con cada lectura rellenada. Los valores escritos
son únicos, y una cuarta parte de las transacciones escribe dos veces la misma clave (el primer
valor es *intermedio*). Dos claves calientes reciben la mitad de las operaciones.

Las particiones llegan al azar, como en producción: un nodo queda aislado de los otros dos; los
clientes siguen llegando a él, así que cada transacción debe seguir teniendo respuesta
(disponibilidad total). La primera siempre aísla un nodo entre 0:20 y 0:30.

```
uv run python -m live transactions --lang es            # míralo; edita es/main.py y guarda
uv run python -m live transactions --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/transactions            # x = aún no, X = hecho
```

Dos dibujos: `cluster` (el de siempre: los nodos y los mensajes entre ellos) y `lanes`
(lo que ven los clientes: sus peticiones esperando, la red como una puerta, el clúster como
un solo servidor). Pulsa `v` para cambiar, o empieza con `--view lanes`.

| Etapa | Reto | En `es/main.py` | Lo que ves |
|---|---|---|---|
| 0 Un solo nodo (dada) | 6a | cada nodo tiene su propio almacén | los nodos siempre van atrasados (~45% al día) |
| 1 Replicado | 6b, sin particiones | envía cada escritura a los demás nodos | al día, pero tras una partición algunas claves nunca se recuperan (~90-95%), y las escrituras se intercalan (G0) |
| 2 Read uncommitted | 6b, con particiones | reenvía hasta que confirmen; gana el sello más nuevo (uno por transacción) | todos se ponen al día, sin G0, pero los lectores ven valores intermedios (G1b) |
| 3 Read committed | 6c | replica transacciones enteras (valores finales), aplicadas de una vez | sin G0 ni G1a, G1b o G1c, y cada nodo se pone al día |

Objetivos, evaluados en cada partición: **al día** ≥ 95% en la calma anterior (la parte de las
claves, en cada nodo, que está a menos de 1 s del valor más nuevo en cualquier nodo);
**respondidas** ≥ 99% de las transacciones durante ella; **recuperado** ≥ 99% al día entre 5 y
10 s después de que termine; **sin escrituras G0** (etapa 2) y **sin lecturas G1** (etapa 3),
ambas desde 15 s antes hasta 5 s después.

El comprobador mira el `self.store` de cada nodo cada 50 ms, fuera de la red, y comprueba lo que
prohíben los retos 6b y 6c de Fly.io:
- **G0, escritura sucia** (read uncommitted ya la prohíbe): anota cada escritura en un almacén
  en el momento; dos transacciones que escribieron x e y, aplicadas T y luego U en x pero U y
  luego T en y en algún nodo, intercalaron sus escrituras. Un sello por transacción lo evita.
- **G1a, lectura abortada**: un nodo puede abortar una transacción (código de error 30,
  `txn-conflict`); una lectura posterior que devuelva una de sus escrituras es una G1a.
- **G1b, lectura intermedia**: una lectura que devuelve un valor que otra transacción sobrescribió
  ella misma.
- **G1c, flujo circular de información**: dos transacciones que leen cada una la escritura de la
  otra. Solo se comprueban ciclos de dos, no más largos.

También se comprueba cada respuesta, como Maelstrom: un `txn_ok` debe llevar las mismas
microoperaciones en orden, con las escrituras repetidas y las lecturas rellenas; si no, cuenta
como no respondida.

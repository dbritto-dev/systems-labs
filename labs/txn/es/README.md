# Laboratorio: txn (Gossip Glomers n.º 6 de Fly.io)

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
uv run python -m live txn --lang es            # míralo; edita es/main.py y guarda
uv run python -m live txn --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/txn            # x = aún no, X = hecho
```

| Etapa | Reto | En `es/main.py` | Lo que ves |
|---|---|---|---|
| 0 Un solo nodo (dada) | 6a | cada nodo tiene su propio almacén | los nodos siempre van atrasados (~45% al día) |
| 1 Replicado | 6b | envía cada escritura a los demás nodos | al día, pero tras una partición algunas claves nunca se recuperan (~90-95%) |
| 2 Lectura no confirmada | 6b + particiones | reenvía hasta el ack; gana el sello más nuevo | todos se ponen al día, pero los lectores ven valores intermedios (G1b) |
| 3 Lectura confirmada | 6c | replica transacciones enteras (valores finales), aplicadas de una vez | sin lecturas intermedias, y cada nodo se pone al día |

Objetivos, evaluados en cada partición: **al día** ≥ 95% en la calma anterior (la parte de las
claves, en cada nodo, que está a menos de 1 s del valor más nuevo en cualquier nodo);
**respuestas** ≥ 99% de las transacciones durante ella; **recuperado** ≥ 99% al día entre 5 y
10 s después de que termine; **sin lecturas G1b** desde 15 s antes hasta 5 s después.

El comprobador mira el `self.store` de cada nodo cada 50 ms, fuera de la red, y revisa cada
lectura que reciben los clientes: una lectura que devuelve el valor intermedio de otra
transacción es una G1b. No busca G0 directamente: un único sello por transacción con "gana la
última escritura" da a cada clave el mismo orden de escrituras en todos los nodos, y eso es lo
que descarta G0.

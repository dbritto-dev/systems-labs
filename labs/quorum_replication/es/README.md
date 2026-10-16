# Laboratorio: quórums

*[Read in English](../README.md)*

Replicación sin líder, como la hacen Amazon Dynamo, Cassandra y Riak, en Python sobre una red
simulada: 5 nodos, ~100 ms por mensaje. Cada clave vive en 3 de ellos (N=3). Los clientes
envían `put` y `get` a cualquier nodo sano, que coordina la petición. Los incidentes llegan al
azar, como en producción: un nodo se cae (y vuelve con sus datos viejos), la red lo aísla o se
vuelve muy lento. El balanceador deja de enviarle clientes, pero sigue siendo réplica de 3/5
de las claves. El primer incidente siempre tumba n2 entre 0:20 y 0:30.

```
uv run python -m live quorum_replication --lang es            # míralo; edita es/main.py y guarda
uv run python -m live quorum_replication --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/quorum_replication            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Una copia (dada) | cada nodo guarda lo que le envían | las lecturas caen en otros nodos y no ven la última escritura |
| 1 Quórums | escribe en W=2 de 3 réplicas, lee de R=2, gana la versión más nueva | ninguna lectura vieja, ni con un nodo caído; pero vuelve atrasado |
| 2 Quórums + reparación | hinted handoff (y read repair) | el nodo que volvió se pone al día en segundos |

Objetivos, evaluados en cada incidente: lecturas viejas = 0 (desde 15 s antes hasta su final), ≥ 99% de
peticiones respondidas durante él, ≥ 99% de las claves al día en todas sus réplicas 10 s
después de que termine, y menos de 10 mensajes entre nodos por operación de cliente (en los
15 s anteriores).

Una lectura es *vieja* cuando devuelve un valor más antiguo que uno cuya escritura se confirmó
antes de que empezara la lectura. Una clave está *al día* cuando sus 3 réplicas guardan el
mismo valor; el comprobador mira el `self.store` de cada nodo cada 250 ms, fuera de la red, y
se salta las claves escritas en el último segundo. El read repair por sí solo no basta para la etapa
2: solo arregla las claves que alguien lee.

Cómo habla tu nodo está en `core/net.py`: `self.reply`, `self.send`, `await self.rpc`,
`self.every`, `self.spawn`, `self.now()` y los manejadores `on_<tipo>`.

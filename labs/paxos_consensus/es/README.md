# Laboratorio: paxos (un log replicado, varios proponentes)

*[Read in English](../README.md)*

[Paxos](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf), en Python, sobre una red
simulada: 5 nodos, ~20 ms por mensaje. Llevan un log replicado de cambios de configuración: cada
hueco (0, 1, 2, ...) guarda un comando. Los clientes envían `command` (un número nuevo) a
cualquier nodo, así que varios nodos proponen a la vez. Un nodo responde al cliente cuando el
comando está decidido en un hueco y aplicado (con todos los huecos anteriores decididos). Todos
los nodos deben decidir el mismo comando en cada hueco, y ningún comando confirmado al cliente
puede desaparecer. Los incidentes llegan al azar, como en producción: el líder se cae a mitad de
una ronda, se cae otro nodo, la red pierde y retrasa mensajes, una partición aísla al líder con un
nodo, o el líder se detiene unos segundos (una pausa del recolector de basura) y despierta seguro
aún de que lidera. El primero es siempre el líder cayéndose a mitad de ronda a las 0:20 (vuelve a
las 0:30).

```
uv run python -m live paxos_consensus --lang es            # míralo; edita es/main.py y guarda
uv run python -m live paxos_consensus --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/paxos_consensus            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Gana la primera propuesta (dada) | cada nodo se queda con el primer valor que oye para un hueco | puntos morados de proponer compiten; nodos rojos: unos decidieron un comando y otros otro |
| 1 Paxos por hueco | `on_prepare`, `on_accept`, `submit`, `paxos`: boletas, promesas, adoptar el valor aceptado más alto | nada se parte, pero hay preparar naranjas en cada comando, los proponentes se pisan y más de 100 mensajes por comando |
| 2 Multi-Paxos | `campaign`, `phase2`, `on_heartbeat`, `tick` y las redirecciones de `on_command`: un líder, la fase 1 una vez, no-ops en los huecos vacíos, espera aleatoria | un líder verde; ~13 mensajes por comando; un líder nuevo en menos de un segundo tras una caída |

Objetivos, evaluados en cada incidente: un log para todos (ningún hueco decidido de dos formas,
desde 15 s antes hasta 5 s después), nada perdido (cada comando confirmado al cliente está en el
log que decidió la mayoría de los nodos), el 95% de los comandos decididos en menos de 2 s durante
el incidente y los 5 s siguientes, y como mucho 16 mensajes entre nodos por comando decidido en la
calma de antes.

El comprobador vigila los diccionarios `decided` y `accepted` de cada nodo (fuera de la red, así
que no añade tráfico): dos valores distintos decididos en un hueco, o un valor decidido distinto
del que aceptó una mayoría de aceptadores (el elegido), es un desacuerdo. Una caída conserva solo
lo que Paxos guarda en disco (`promised`, `accepted`, `decided`). La primera caída está preparada
para doler: el líder deja de leer la red, los accept de un hueco se pierden con él, y los de los
dos huecos siguientes llegan a todos. Esos dos quedan elegidos sin que nadie lo sepa, con un hueco
vacío antes: un líder nuevo debe volver a proponerlos y llenar el hueco con un no-op.

Cómo habla tu nodo está en `core/net.py`: `self.reply`, `await self.rpc`, `self.spawn`,
`self.every`, `self.now()` y los manejadores `on_<tipo>`; `es/main.py` añade `broadcast`,
`learn`, `decide` y las ayudas de boletas.

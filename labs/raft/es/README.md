# Laboratorio: raft (elección de líder y replicación del log)

*[Read in English](../README.md)*

[Raft](https://raft.github.io/), en Python, sobre una red simulada: 5 nodos, ~20 ms por
mensaje. Los clientes envían `command` (un número nuevo) al nodo que creen que lidera; un
seguidor los redirige. Los nodos deben acordar un único log ordenado, responder a un cliente
solo cuando su comando está en una mayoría, y no perder nunca un comando confirmado. Los
incidentes llegan al azar, como en producción: el líder queda aislado con un seguidor, el host
del líder se cae y se reinicia, o la red se vuelve lenta. El primero siempre aísla al líder
entre 0:20 y 0:30.

```
uv run python -m live raft --lang es            # míralo; edita es/main.py y guarda
uv run python -m live raft --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/raft            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Sin líder (dada) | guarda el estado, redirige a los clientes | todos los nodos siguen azules; todo comando falla |
| 1 Elección de líder | timeouts aleatorios, RequestVote, latidos | un líder verde; uno nuevo en ~0,5 s tras un corte, pero los comandos confirmados solo están en el líder |
| 2 Replicación del log | AppendEntries, confirma en una mayoría | cada comando en una mayoría; al cerrarse el corte el líder viejo sobrescribe entradas confirmadas |
| 3 Seguro | cede ante un término mayor, rechaza líderes viejos, vota solo a logs al día | nada perdido, nunca |

Objetivos, juzgados por incidente: un líder en la calma de antes (el 95% del tiempo), un líder
nuevo en menos de 2 s cuando afecta al líder, el 99% de los comandos confirmados en la calma y
ninguno confirmado al cliente sin estar en una mayoría, ningún comando confirmado perdido (hasta
5 s después de que acabe), y el 95% de los comandos confirmados durante el incidente.

El verificador lee `role`, `current_term` y `log` de cada nodo cada 50-100 ms, fuera de la red,
así que no añade tráfico. Un comando está confirmado cuando una mayoría tiene la misma entrada en
la misma posición; se pierde si un nodo que la tenía ya no la tiene. Una caída conserva solo lo
que Raft persiste (`current_term`, `voted_for`, `log`). Una partición se cierra primero en un
sentido: durante 0,5 s al lado aislado se le oye antes de que él oiga, y ahí es cuando un líder
que ignora los términos hace el daño.

Cómo habla tu nodo está en `core/net.py`: `self.reply`, `await self.rpc`, `self.spawn`,
`self.every`, `self.now()` y los manejadores `on_<tipo>`.

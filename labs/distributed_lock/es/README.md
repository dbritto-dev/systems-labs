# Laboratorio: cerrojo distribuido

*[Read in English](../README.md)*

Cuatro workers comparten un informe en un servicio de almacenamiento, y solo un trabajo puede
escribirlo a la vez, así que un trabajo primero toma un cerrojo de un servicio de cerrojos: el
problema de [How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html),
de Martin Kleppmann, en Python sobre una red simulada (~50 ms por mensaje). Los clientes reparten
~0.8 trabajos por segundo a cualquier worker sano; el worker toma el cerrojo, escribe el informe
en 3 partes, lo suelta y responde. Los incidentes llegan al azar, como en producción, y golpean
al trabajo que tiene el cerrojo en el peor momento: se **congela** (una pausa de recolección de
basura, una migración de máquina virtual, memoria pasada a disco), **se cae** con el cerrojo, su
**escritura se queda en la red** (retransmisiones de TCP, un enlace congestionado), o queda
**aislado** del servicio de cerrojos. El primer incidente es siempre una pausa de 10 s, desde la
primera escritura después de 0:20.

```
uv run python -m live distributed_lock --lang es            # míralo; edita es/main.py y guarda
uv run python -m live distributed_lock --lang es --lesson   # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/distributed_lock            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Qué ves |
|---|---|---|
| 0 Cerrojo simple (dado) | el cerrojo se tiene hasta que se suelta | un dueño congelado atasca todos los trabajos durante toda la pausa (~10.8 s); uno caído o aislado, para siempre |
| 1 Plazos (leases) | el cerrojo caduca `LEASE` (2 s) después de darlo o de la última renovación; el dueño renueva cada `LEASE / 3` | atascos de 2.4–4.2 s; pero cuando el dueño congelado despierta, su escritura cae sobre datos más nuevos: 1 escritura corrupta por pausa o escritura tardía |
| 2 Plazos + tokens de vallado (fencing tokens) | cada concesión trae un token uno mayor; las escrituras lo llevan; el almacenamiento rechaza uno más viejo | la misma escritura tardía se rechaza: 0 escrituras corruptas, atascos acotados, ~100% de trabajos hechos |

Metas, juzgadas por incidente: escrituras corruptas = 0 (desde 15 s antes hasta 10 s después),
atasco ≤ 5 s (el tramo más largo con trabajos esperando y ninguno terminando, desde su inicio
hasta 10 s después), y trabajos hechos ≥ 80% (de los pedidos en ese tramo; un cliente se rinde
a los 10 s).

Una escritura es *corrupta* cuando el almacenamiento la acepta después de que un trabajo que
tomó el cerrojo más tarde ya tuvo una escritura aceptada: el comprobador mira los mensajes
`acquire_ok` y `write_ok`, fuera de tu código. Mirar tu propio reloj antes de escribir no ayuda:
la pausa llega justo después de que un worker decide escribir, como lo describe Kleppmann.

La gráfica muestra los mensajes del cerrojo (el sondeo mientras está tomado: una joroba quiere
decir que los trabajos están atascados) y las escrituras, por segundo.

**Dos dibujos.** Se abre con **clúster**: el servicio de cerrojos (arriba a la izquierda), el
almacenamiento (abajo a la izquierda) y los workers w1..w4. Los mensajes del cerrojo vuelan en
azul y las escrituras en blanco (naranja claro mientras una se queda en la red); el dueño es
verde, un worker congelado naranja (sus escrituras esperan justo a su lado), uno caído o aislado
rojo. Una escritura tardía que el almacenamiento aceptó estalla en rojo junto a él, una que
rechazó en naranja; bajo la cuadrícula, el estado y quién recibió el cerrojo por última vez.
Pulsa `v` (o `--view lanes`) para **carriles**: los trabajos esperan el cerrojo (la puerta,
cerrada mientras está atascado) delante del almacenamiento; las escrituras tardías llegan en
rojo (aceptadas) o naranja (rechazadas).

Cómo hablan tus nodos está en `core/net.py`: `self.reply`, `self.send`, `await self.rpc`,
`self.spawn`, `self.now()`, y los manejadores `on_<type>`.

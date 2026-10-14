# Laboratorio: detección de fallos

*[Read in English](../README.md)*

Cómo se pone de acuerdo un clúster en quién está muerto, como lo hacen Cassandra, Akka, Consul y
Serf, en Python sobre una red simulada: 8 nodos, ~50 ms por mensaje. Cada nodo ejecuta tu
`Detector` y guarda `self.status`: lo que piensa de cada otro nodo (`"alive"`, `"suspect"` o
`"dead"`). Un nodo sale del clúster en cuanto un nodo sano lo declara muerto, y los clientes se
enrutan según esa vista: cada sesión tiene un nodo de casa, y pasa al siguiente nodo cuando la
vista dice que está muerto.

La red nunca está limpia: cuatro enlaces (n0-n5, n1-n7, n3-n6, n4-n7) pasan por un switch viejo y
pierden la mitad de sus mensajes. Además, los incidentes llegan al azar, como en producción: un
nodo se cae (y rearranca), se vuelve lento (cada mensaje hacia él o desde él tarda 3-5 veces más),
pierde el 15-30% de sus mensajes, o queda aislado de 2 o 3 de los otros mientras el resto aún llega
a él (una partición parcial). Solo la caída debería acabar en una muerte. El primer incidente
siempre tumba n2 entre 0:20 y 0:30.

```
uv run python -m live failure_detection --lang es            # míralo; edita es/main.py y guarda
uv run python -m live failure_detection --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/failure_detection            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Timeout fijo (dada) | latidos a todos cada 0.25 s, muerto tras 1 s de silencio | los nodos tras los enlaces que pierden se ponen rojos una y otra vez; con un timeout de 3 s, las caídas se hallan 3 s tarde |
| 1 Phi accrual | `phi(intervals, elapsed)`: juzga cada silencio por la historia de ese par | caídas halladas en menos de un segundo, enlaces que pierden tolerados; pero 28 mensajes por nodo y segundo, y una partición parcial aún entierra un nodo |
| 2 SWIM | ping a un par por periodo, `ping_req` a través de K ayudantes, sospecha antes de matar | pocos mensajes por nodo; los sondeos indirectos rodean los enlaces rotos |

Objetivos, evaluados por incidente: una caída se declara muerta en 2.5 s como mucho (por algún
nodo sano), ningún nodo sano se declara muerto desde 15 s antes del incidente hasta 5 s después,
y cada nodo envía menos de 10 mensajes por segundo (en los 15 s anteriores).

Dos dibujos (tecla `v`): **clúster**, cada nodo del color que le da el clúster (azul vivo, naranja
sospechoso, rojo declarado muerto, gris caído pero aún sin notar), los sondeos en azul, los
sondeos indirectos en naranja claro, los mensajes perdidos en rojo; y **carriles**, lo que ven los
clientes: verde las respuestas del nodo de casa, naranja claro tras pasar a otro nodo porque el de
casa está muerto, naranja oscuro tras un cambio inútil porque declararon muerto a un nodo sano,
rojo cuando el nodo de casa se cayó y el enrutador aún no lo sabía.

El comprobador lee el `self.status` de cada nodo cada 250 ms, por fuera de la red. El clúster
lleva 30 s funcionando cuando la ejecución empieza en 0:00, así que los detectores tienen una
historia de la que aprender. Un nodo que vuelve de una caída tiene 3 s para reincorporarse antes de
que cuente su vista.

Cómo habla tu nodo está en `core/net.py`: `self.send`, `self.reply`, `await self.rpc`,
`self.every`, `self.spawn`, `self.now()` y los manejadores `on_<type>`.

# Laboratorio: bandeja de salida transaccional

*[Read in English](../README.md)*

Los clientes hacen ~50 pedidos por segundo a través de tu `OrderService.place_order(order)`. Cada
pedido guardado debe llegar a envíos como un evento OrderPlaced en el intermediario de mensajes,
exactamente una vez en efecto: envíos (tu `ShippingConsumer.handle(event)`) crea un envío por
pedido. El pod del servicio de pedidos también ejecuta tu `Relay` (el publicador); envíos es otro
servicio que lee el topic en orden y consolida su offset cada segundo.

En momentos al azar, como en producción, el proceso del servicio de pedidos muere una y otra vez
(sin memoria, un despliegue sin apagado ordenado, un nodo perdido: las transacciones abiertas se
deshacen, el publicador muere también, y vuelve tras 1 s), el intermediario está caído (un líder
perdido, un certificado caducado, un disco lleno), falla una parte de las consolidaciones de
pedidos (interbloqueos, timeouts de bloqueo, un failover), solo el publicador muere una y otra vez,
o el grupo de consumidores de envíos se reparte una y otra vez (vuelve a su último offset
consolidado, con un `ShippingConsumer` nuevo). Una muerte llega entre dos pasos del trabajo: justo
después de que se confirme una publicación, o justo después de una consolidación. La ejecución
nunca se reinicia. El primer incidente siempre es un bucle de muertes entre 0:20 y 0:30.

```
uv run python -m live transactional_outbox --lang es            # míralo; edita es/main.py y guarda
uv run python -m live transactional_outbox --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/transactional_outbox            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Doble escritura (dada) | guarda el pedido y publica el evento en la transacción de la petición; si el intermediario está caído, sigue adelante | una muerte después de publicar deja un fantasma (un evento de un pedido que se deshizo, rojo); una caída del intermediario pierde el evento de cada pedido guardado durante ella |
| 1 Bandeja de salida | `tx.insert("outbox", event)` en la transacción del pedido, sin publicar; `Relay.relay_once`: `fetch_unsent`, publica cada uno, `mark_sent` | nada se pierde ni se inventa; la bandeja se llena mientras el intermediario está caído y se vacía después; pero una muerte entre publicar y marcar, o un reparto, envía algunos pedidos dos veces (naranja oscuro) |
| 2 Consumidor idempotente | en la transacción de `handle`, salta un id de evento que esté en "processed"; si no, anótalo junto con el envío | las repeticiones siguen llegando y se descartan (gris); todos los objetivos OK |

Objetivos, evaluados en cada incidente: base correcta (antes: ≥ 99% de los pedidos guardados
llegaron a envíos), eventos perdidos = 0 (guardados durante el incidente y que nunca llegaron a
envíos, con 15 s para llegar), eventos fantasma = 0 (publicados para un pedido que nunca se
guardó), enviados dos veces = 0 (durante y 5 s después), y retraso p99 < 3 s (desde que se guarda
un pedido hasta que envíos lo ve, para los pedidos guardados en los 10 s siguientes).

Primero se abre el dibujo de clúster: arriba el servicio, su base de datos y el publicador; abajo envíos
y el intermediario. El dibujo de carriles muestra los pedidos en la puerta del servicio de pedidos,
y la bandeja pendiente como el indicador del servidor. Pulsa `v` para cambiar.

- **¿Por qué no guardar, consolidar y luego publicar?** Solo mueve el hueco. Una muerte después de
  consolidar y antes de publicar pierde el evento (el laboratorio lo prueba: justo después de una
  consolidación). No hay orden de dos escrituras en dos sistemas que aguante una caída entre ellas.
- **¿Por qué publicar antes de marcar como enviado?** Si marcas primero, una muerte entre medias
  pierde el evento para siempre. Si publicas primero, lo peor es un duplicado, que el consumidor
  puede descartar. Por eso envíos tiene que ser idempotente: entregar al menos una vez es lo mejor
  que un publicador puede prometer.
- **¿Por qué en la misma transacción en envíos?** Si anotas el id del evento en otra transacción,
  un fallo entre las dos o se salta un envío o envía dos veces. Un set en memoria se pierde cuando
  un reparto pasa el topic a un consumidor nuevo.
- **¿Por qué el objetivo de retraso?** Un publicador que se echa siestas o publica pocas filas por vuelta
  no puede vaciar lo acumulado en una caída del intermediario: los eventos no se pierden, pero
  llegan tarde. Publica por lotes.

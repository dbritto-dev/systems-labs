"""Laboratorio transactional_outbox: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los clientes hacen ~50 pedidos por segundo a través de `OrderService.place_order(order)`. Cada
pedido debe guardarse en nuestra base de datos Y anunciarse como un evento OrderPlaced en el
intermediario de mensajes, para que envíos (tu `ShippingConsumer`) lo envíe. Ahora mismo el
servicio de pedidos hace una doble escritura: guarda el pedido y publica el evento, dos sistemas,
sin una transacción común. Cuando el proceso muere entre las dos, el intermediario está caído, o
la consolidación falla después de publicar, los eventos se pierden (un pedido que nadie envía) o se
publican para pedidos que nunca se guardaron (un envío fantasma).

Haz las etapas en orden, en este archivo:

  Etapa 1  Bandeja de salida transaccional: escribe el evento en la tabla "outbox" EN LA MISMA
           transacción que el pedido, y nunca publiques desde place_order. Un publicador
           (`Relay.relay_once`) lee las filas sin enviar, las publica y las marca como enviadas.
           Publica primero, marca después: si el publicador muere entre medias, las filas se publican
           otra vez (al menos una vez), así que aparecen duplicados.
  Etapa 2  Consumidor idempotente: envíos recuerda los ids de los eventos que ya ha tratado, en la
           MISMA transacción que el envío, y salta un evento que ya ha visto. Cada pedido se envía
           exactamente una vez en efecto.

Lo que tienes (mira labs/transactional_outbox/api.py):
  async with self.db.transaction() as tx:     se consolida todo junto al acabar el bloque, o nada
      await tx.insert(table, row)             row = {"id": ..., ...}; DuplicateKey si el id existe
      await tx.get(table, id) -> fila | None
  await self.db.fetch_unsent(limit) -> [evento, ...]    await self.db.mark_sent([ids de evento])
  await self.broker.publish(event)            BrokerUnavailable cuando el intermediario está caído
  new_id("evt") -> "evt-123"

El proceso puede morir en cualquier momento (sin memoria, un despliegue, un nodo perdido): un
proceso muerto ya no ejecuta nada, y sus transacciones abiertas se deshacen. No guardes nada
importante en memoria.

Compruébalo:  LABS_LANG=es uv run pytest labs/transactional_outbox
Mira una solución (¡después de intentarlo!):  labs/transactional_outbox/es/reference.py
"""

from __future__ import annotations

from labs.transactional_outbox.api import BrokerUnavailable, DuplicateKey, new_id  # noqa: F401

BATCH = 100  # filas de la bandeja que el publicador publica por vuelta


class OrderService:
    """Guarda un pedido y lo anuncia.

    Contrato:
      - `await service.place_order(order)`: order es {"id": "ord-...", "customer": int, "total": int}.
        Guárdalo en la tabla "orders". Devuelve con normalidad si se guardó; deja salir una excepción
        si no (CommitFailed, BrokerUnavailable, ...): el cliente ve un error.
      - Cada pedido guardado recibe, tarde o temprano, exactamente un evento OrderPlaced para envíos:
        {"id": new_id("evt"), "type": "OrderPlaced", "order_id": order["id"], "total": order["total"]}
      - Ningún evento para un pedido que no se guardó.
    """

    def __init__(self, db, broker) -> None:
        self.db = db
        self.broker = broker

    async def place_order(self, order: dict) -> None:
        event = {"id": new_id("evt"), "type": "OrderPlaced", "order_id": order["id"], "total": order["total"]}
        # La transacción de la petición (como ATOMIC_REQUESTS de Django): se consolida al acabar el bloque.
        async with self.db.transaction() as tx:
            await tx.insert("orders", order)  # guarda ...
            try:
                await self.broker.publish(event)  # ... y luego publica
            except BrokerUnavailable:
                pass  # "no hagas fallar el pedido porque el intermediario va mal": el evento se pierde
            # Al salir del bloque se consolida. La consolidación aún puede fallar (un interbloqueo), o el
            # proceso puede morir antes: entonces el pedido no se guarda, pero envíos ya tiene el evento.
        #
        # Etapa 1: cambia la publicación por `await tx.insert("outbox", event)` dentro del bloque.
        #          Así el pedido y su evento se guardan juntos, o ninguno.


class Relay:
    """Etapa 1. Lleva los eventos de la tabla outbox al intermediario.

    El escenario llama a `await relay.relay_once()` una y otra vez: enseguida si devolvió un número
    mayor que 0, tras una pausa corta (0.1 s) si devolvió 0, y tras 0.5 s si lanzó
    BrokerUnavailable. Tras una muerte crea un Relay nuevo: guarda tu progreso en la base de datos.

      relay_once()  trae hasta BATCH filas sin enviar (`fetch_unsent`), publica cada una y luego
                    marca como enviadas las publicadas (`mark_sent`); devuelve cuántas publicó.
                    Si el intermediario falla a mitad, marca las que llegaron y vuelve a lanzar.
    """

    def __init__(self, db, broker) -> None:
        self.db = db
        self.broker = broker

    async def relay_once(self) -> int:
        # Etapa 1: events = await self.db.fetch_unsent(BATCH)
        #          publícalos uno a uno, guardando los ids que llegaron; luego
        #          `await self.db.mark_sent(ids)`. Nunca marques antes de publicar: una muerte entre
        #          medias perdería el evento. Usa try/finally para que un fallo del intermediario
        #          marque igualmente las que llegaron.
        raise NotImplementedError("PENDIENTE etapa 1: Relay.relay_once")


class ShippingConsumer:
    """Envíos: un envío por pedido. Lee el topic en orden y llama a `handle` por cada evento.

    El intermediario entrega al menos una vez: tras reiniciarse el publicador o repartirse el grupo de
    consumidores, el mismo evento puede llegar otra vez, y un reparto puede pasar el topic a un
    ShippingConsumer nuevo.

      handle(event)  crea el envío del pedido (una vez por pedido, llegue el evento las veces que llegue)
    """

    def __init__(self, db) -> None:
        self.db = db

    async def handle(self, event: dict) -> None:
        async with self.db.transaction() as tx:
            # Etapa 2: en esta misma transacción, primero busca el evento:
            #          `if await tx.get("processed", event["id"]) is not None: return`
            #          y luego anótalo: `await tx.insert("processed", {"id": event["id"]})`.
            #          (Un set en self no basta: un reparto te da un ShippingConsumer nuevo.)
            await tx.insert("shipments", {"id": new_id("shp"), "order_id": event["order_id"]})

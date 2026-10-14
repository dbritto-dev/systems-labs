"""Laboratorio transactional_outbox: una solución que funciona. Léela después de intentar main.py."""

from __future__ import annotations

from labs.transactional_outbox.api import BrokerUnavailable, DuplicateKey, new_id  # noqa: F401

BATCH = 100  # filas de la bandeja que el relé publica por vuelta


class OrderService:
    def __init__(self, db, broker) -> None:
        self.db = db
        self.broker = broker

    async def place_order(self, order: dict) -> None:
        event = {"id": new_id("evt"), "type": "OrderPlaced", "order_id": order["id"], "total": order["total"]}
        # Una transacción, una base de datos: el pedido y su evento se guardan juntos, o ninguno.
        async with self.db.transaction() as tx:
            await tx.insert("orders", order)
            await tx.insert("outbox", event)


class Relay:
    def __init__(self, db, broker) -> None:
        self.db = db
        self.broker = broker

    async def relay_once(self) -> int:
        events = await self.db.fetch_unsent(BATCH)
        sent = []
        try:
            for event in events:
                await self.broker.publish(event)  # primero publica ...
                sent.append(event["id"])
        finally:
            if sent:
                await self.db.mark_sent(sent)  # ... y marca después: una muerte entre medias lo publica otra vez
        return len(sent)


class ShippingConsumer:
    def __init__(self, db) -> None:
        self.db = db

    async def handle(self, event: dict) -> None:
        # La anotación y el envío se consolidan juntos: un evento se trata una vez, o ninguna.
        async with self.db.transaction() as tx:
            if await tx.get("processed", event["id"]) is not None:
                return  # ya visto: una reentrega
            await tx.insert("processed", {"id": event["id"]})
            await tx.insert("shipments", {"id": new_id("shp"), "order_id": event["order_id"]})

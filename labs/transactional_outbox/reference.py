"""Lab transactional_outbox: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

from labs.transactional_outbox.api import BrokerUnavailable, DuplicateKey, new_id  # noqa: F401

BATCH = 100  # outbox rows the relay publishes per round


class OrderService:
    def __init__(self, db, broker) -> None:
        self.db = db
        self.broker = broker

    async def place_order(self, order: dict) -> None:
        event = {"id": new_id("evt"), "type": "OrderPlaced", "order_id": order["id"], "total": order["total"]}
        # One transaction, one database: the order and its event are saved together, or neither is.
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
                await self.broker.publish(event)  # publish first ...
                sent.append(event["id"])
        finally:
            if sent:
                await self.db.mark_sent(sent)  # ... mark after: a kill in between publishes it again
        return len(sent)


class ShippingConsumer:
    def __init__(self, db) -> None:
        self.db = db

    async def handle(self, event: dict) -> None:
        # The dedupe record and the shipment commit together: an event is handled once, or not at all.
        async with self.db.transaction() as tx:
            if await tx.get("processed", event["id"]) is not None:
                return  # seen it: a redelivery
            await tx.insert("processed", {"id": event["id"]})
            await tx.insert("shipments", {"id": new_id("shp"), "order_id": event["order_id"]})

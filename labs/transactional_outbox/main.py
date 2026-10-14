"""Lab transactional_outbox: YOUR FILE. Edit it and save; the live window reruns it.

Customers place ~50 orders a second through `OrderService.place_order(order)`. Each order must
be saved in our database AND announced as an OrderPlaced event on the broker, so shipping (your
`ShippingConsumer`) ships it. Right now the order service does a dual write: it saves the order
and publishes the event, two systems, no shared transaction. When the process is killed between
the two, the broker is down, or the commit fails after the publish, events get lost (an order
nobody ships) or published for orders that were never saved (a phantom shipment).

Do the stages in order, in this file:

  Stage 1  Transactional outbox: write the event to the "outbox" table IN THE SAME transaction as
           the order, and never publish from place_order. A relay (`Relay.relay_once`) reads
           unsent outbox rows, publishes them, and marks them sent. Publish first, mark after:
           if the relay dies in between, the rows are published again (at-least-once), so
           duplicates appear.
  Stage 2  Idempotent consumer: shipping remembers the ids of the events it has handled, in the
           SAME transaction as the shipment, and skips an event it has already seen. Every order
           is shipped exactly once in effect.

What you get (see labs/transactional_outbox/api.py):
  async with self.db.transaction() as tx:     committed together when the block ends, or not at all
      await tx.insert(table, row)             row = {"id": ..., ...}; DuplicateKey if the id exists
      await tx.get(table, id) -> row | None
  await self.db.fetch_unsent(limit) -> [event, ...]    await self.db.mark_sent([event ids])
  await self.broker.publish(event)            BrokerUnavailable when the broker is down
  new_id("evt") -> "evt-123"

The process can be killed at any moment (an OOM kill, a deploy, a lost node): a killed process
runs nothing more, and its open transactions roll back. Keep nothing important in memory.

Check yourself:  uv run pytest labs/transactional_outbox
Peek at a solution (after trying!):  labs/transactional_outbox/reference.py
"""

from __future__ import annotations

from labs.transactional_outbox.api import BrokerUnavailable, DuplicateKey, new_id  # noqa: F401

BATCH = 100  # outbox rows the relay publishes per round


class OrderService:
    """Saves an order and announces it.

    Contract:
      - `await service.place_order(order)`: order is {"id": "ord-...", "customer": int, "total": int}.
        Save it in the "orders" table. Return normally if it was saved; let an exception out if not
        (CommitFailed, BrokerUnavailable, ...): the customer sees an error.
      - Every saved order gets exactly one OrderPlaced event to shipping, eventually:
        {"id": new_id("evt"), "type": "OrderPlaced", "order_id": order["id"], "total": order["total"]}
      - No event for an order that was not saved.
    """

    def __init__(self, db, broker) -> None:
        self.db = db
        self.broker = broker

    async def place_order(self, order: dict) -> None:
        event = {"id": new_id("evt"), "type": "OrderPlaced", "order_id": order["id"], "total": order["total"]}
        # The request's transaction (like Django's ATOMIC_REQUESTS): it commits when the block ends.
        async with self.db.transaction() as tx:
            await tx.insert("orders", order)  # save ...
            try:
                await self.broker.publish(event)  # ... then publish
            except BrokerUnavailable:
                pass  # "don't fail the order because the broker is flaky": the event is gone
            # Leaving the block commits. The commit can still fail (a deadlock), or the process can
            # be killed before it: then the order is not saved, but shipping already got the event.
        #
        # Stage 1: replace the publish with `await tx.insert("outbox", event)` inside the block.
        #          The order and its event are then saved together, or neither is.


class Relay:
    """Stage 1. Moves events from the outbox table to the broker.

    The scenario calls `await relay.relay_once()` again and again: right away when it returned a
    number above 0, after a short pause (0.1 s) when it returned 0, and after 0.5 s when it raised
    BrokerUnavailable. After a kill it makes a new Relay: keep your progress in the database.

      relay_once()  fetch up to BATCH unsent rows (`fetch_unsent`), publish each, then mark the
                    published ones sent (`mark_sent`); return how many it published.
                    If the broker fails half way, mark the ones that made it, then raise.
    """

    def __init__(self, db, broker) -> None:
        self.db = db
        self.broker = broker

    async def relay_once(self) -> int:
        # Stage 1: events = await self.db.fetch_unsent(BATCH)
        #          publish them one by one, keeping the ids that made it; then
        #          `await self.db.mark_sent(ids)`. Never mark before publishing: a kill in between
        #          would lose the event. Use try/finally so a broker failure still marks the rest.
        raise NotImplementedError("TODO stage 1: Relay.relay_once")


class ShippingConsumer:
    """Shipping: one shipment per order. Reads the topic in order and calls `handle` per event.

    The broker delivers at-least-once: after a relay restart or a consumer group rebalance the same
    event can arrive again, and a rebalance can move the topic to a fresh ShippingConsumer.

      handle(event)  create the order's shipment (once per order, however often the event arrives)
    """

    def __init__(self, db) -> None:
        self.db = db

    async def handle(self, event: dict) -> None:
        async with self.db.transaction() as tx:
            # Stage 2: in this same transaction, first look the event up:
            #          `if await tx.get("processed", event["id"]) is not None: return`
            #          then record it: `await tx.insert("processed", {"id": event["id"]})`.
            #          (A set on self is not enough: a rebalance gives you a new ShippingConsumer.)
            await tx.insert("shipments", {"id": new_id("shp"), "order_id": event["order_id"]})

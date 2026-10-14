import asyncio
import itertools

from core.contract import load
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.transactional_outbox import reference, scenario
from labs.transactional_outbox.api import Broker, BrokerUnavailable, Database, new_id

code = load("transactional_outbox", variant(), scenario.NAMES)


class _ShipEveryTime:  # shipping as given: every delivery is a shipment
    def __init__(self, db):
        self.db = db

    async def handle(self, event):
        async with self.db.transaction() as tx:
            await tx.insert("shipments", {"id": new_id("shp"), "order_id": event["order_id"]})


class SAVE_THEN_PUBLISH:  # the other dual write: commit first, then publish (and shrug if the broker is down)
    class OrderService:
        def __init__(self, db, broker):
            self.db, self.broker = db, broker

        async def place_order(self, order):
            event = {"id": new_id("evt"), "type": "OrderPlaced", "order_id": order["id"], "total": order["total"]}
            async with self.db.transaction() as tx:
                await tx.insert("orders", order)
            try:
                await self.broker.publish(event)
            except BrokerUnavailable:
                pass

    Relay = reference.Relay
    ShippingConsumer = _ShipEveryTime


class OUTBOX:  # stage 1 done: an outbox and a relay, but shipping ships every delivery
    OrderService = reference.OrderService
    Relay = reference.Relay
    ShippingConsumer = _ShipEveryTime


class MARK_FIRST:  # a relay that marks rows sent before publishing them: at-most-once
    OrderService = reference.OrderService

    class Relay(reference.Relay):
        async def relay_once(self):
            events = await self.db.fetch_unsent(100)
            await self.db.mark_sent([e["id"] for e in events])
            for e in events:
                await self.broker.publish(e)
            return len(events)

    ShippingConsumer = reference.ShippingConsumer


class SLOW_RELAY:  # every stage done, but the relay naps between small batches: it never catches up
    OrderService = reference.OrderService

    class Relay(reference.Relay):
        async def relay_once(self):
            events = await self.db.fetch_unsent(20)
            for e in events:
                await self.broker.publish(e)
            await self.db.mark_sent([e["id"] for e in events])
            await asyncio.sleep(0.3)
            return len(events)

    ShippingConsumer = reference.ShippingConsumer


def first(world, v):
    return [r.ok for r in world.runs[v].settled[0]]


def by_kind(world, v):
    run = world.runs[v]
    return {i.kind: [r.ok for r in run.settled[i.index]] for i in reversed(run.incidents)
            if all(r is not None for r in run.settled.get(i.index, [None]))}


# ------------------------------------------------------------- given behaviour


def test_starting_code_publishes_events_for_orders_that_were_never_saved():
    world = build_world("transactional_outbox", "main", 1)
    assert first(world, "main") == [True, True, False, True, True]  # a kill after a publish: phantoms
    assert world.stage_index("main") == 0  # Dual write


def test_saving_then_publishing_loses_events_instead():
    for seed in (1, 6):
        world = build_world("transactional_outbox", SAVE_THEN_PUBLISH, 2, seed=seed)
        assert first(world, SAVE_THEN_PUBLISH) == [True, False, True, True, True]  # a kill after a commit
        assert world.stage_index(SAVE_THEN_PUBLISH) == 0
    assert by_kind(world, SAVE_THEN_PUBLISH)["broker"][1] is False  # seed 6: a broker outage loses events too


def test_an_outbox_without_an_idempotent_consumer_ships_some_orders_twice():
    for seed in (1, 2, 3):
        world = build_world("transactional_outbox", OUTBOX, 1, seed=seed)
        assert first(world, OUTBOX) == [True, True, True, False, True]
        assert world.stage_index(OUTBOX) == 1  # Transactional outbox


def test_marking_rows_sent_before_publishing_loses_events():
    world = build_world("transactional_outbox", MARK_FIRST, 1, seed=2)
    assert first(world, MARK_FIRST)[1] is False
    assert world.stage_index(MARK_FIRST) == 0


def test_a_relay_that_cannot_catch_up_fails_the_lag_goal_after_a_broker_outage():
    world = build_world("transactional_outbox", SLOW_RELAY, 2, seed=6)
    assert world.stage_index(SLOW_RELAY) == 2
    assert by_kind(world, SLOW_RELAY)["broker"] == [True, True, True, True, False]


def test_reference_passes_every_goal_for_ten_minutes():
    world = build_world("transactional_outbox", "reference", 10, seed=4)
    run = world.runs["reference"]
    results = [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
               if all(r is not None for r in run.settled[i])]
    assert len(results) >= 9 and {i.kind for i in run.incidents} == {k.name for k in scenario.KINDS}
    assert all(all(r) for r in results)
    assert world.stage_index("reference") == 2  # Idempotent consumer


def test_reference_lands_on_the_last_stage_on_other_days():
    for seed in (2, 3, 5):
        world = build_world("transactional_outbox", "reference", 1, seed=seed)
        assert all(first(world, "reference")) and world.stage_index("reference") == 2


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world("transactional_outbox", "reference", 7)
    run = world.runs["reference"]
    assert run.keys["orders"] == sorted(run.keys["orders"])
    assert run.keys["orders"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference"), 7)
    orders = sum(len(p["tables"]["orders"]) for p in pieces)
    assert run.total("orders", 1e9) == orders


# ------------------------------------------------------------- your code


def _system():
    published = []
    db = Database()
    broker = Broker(on_publish=lambda event, ok: ok and published.append(event["order_id"]))
    return db, broker, published


def _order(n):
    return {"id": f"ord-{n}", "customer": 7, "total": 1250}


@your_code(1, "place_order saves the order and its event together, and publishes nothing")
def test_stage1_order_and_event_in_one_transaction():
    async def main():
        db, broker, published = _system()
        service = code.OrderService(db, broker)
        await service.place_order(_order(1))
        await service.place_order(_order(2))
        return await db.fetch_unsent(10), published, await db.get("orders", "ord-1")

    unsent, published, saved = run_virtual(main())
    assert published == []  # only the relay publishes
    assert saved is not None and [e["order_id"] for e in unsent] == ["ord-1", "ord-2"]
    assert len({e["id"] for e in unsent}) == 2


@your_code(1, "the relay publishes unsent rows once, and keeps them while the broker is down")
def test_stage1_relay_publishes_and_marks():
    async def main():
        db, broker, published = _system()
        service = code.OrderService(db, broker)
        for n in range(3):
            await service.place_order(_order(n))
        relay = code.Relay(db, broker)
        broker.down = True
        try:
            await relay.relay_once()
            refused = False
        except BrokerUnavailable:
            refused = True
        left = len(await db.fetch_unsent(10))
        broker.down = False
        n = await relay.relay_once()
        again = await code.Relay(db, broker).relay_once()  # a new relay (after a restart) finds nothing
        return refused, left, n, again, published

    refused, left, n, again, published = run_virtual(main())
    assert refused and left == 3  # nothing marked while nothing was published
    assert n == 3 and again == 0 and published == ["ord-0", "ord-1", "ord-2"]


@your_code(1, "nothing lost and no phantom on the first incident")
def test_stage1_first_incident_nothing_lost_or_invented():
    world = build_world("transactional_outbox", variant(), 1)
    assert world.stage_index(variant()) >= 1


@your_code(2, "an event delivered twice ships once, even to a fresh consumer")
def test_stage2_consumer_dedupes():
    async def main():
        db = Database()
        event = {"id": new_id("evt"), "type": "OrderPlaced", "order_id": "ord-1", "total": 1250}
        other = {"id": new_id("evt"), "type": "OrderPlaced", "order_id": "ord-2", "total": 900}
        await code.ShippingConsumer(db).handle(event)
        await code.ShippingConsumer(db).handle(dict(event))  # redelivered after a rebalance
        consumer = code.ShippingConsumer(db)
        await consumer.handle(other)
        await consumer.handle(dict(event))
        return [row["order_id"] for row, _ in db.tables["shipments"].values()]

    assert sorted(run_virtual(main())) == ["ord-1", "ord-2"]


@your_code(2, "every order shipped exactly once on the first incident: every goal OK")
def test_stage2_first_incident_every_goal():
    world = build_world("transactional_outbox", variant(), 1)
    assert first(world, variant()) == [True] * 5


def test_both_pictures_show_the_flow():
    from live.canvas import EXTRA3, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def pictures(v: str):
        world = build_world("transactional_outbox", v, 1)
        assert views_for(world) == ["cluster", "lanes"] and world.view == "cluster"  # cluster opens first
        frames = {}
        for t in (20.5, 22.02, 25.0, 40.0):  # in the crash loop, and after it
            frame = adapter_for(world).frame(v, t)
            assert len(frame.nodes) == 5
            text = "\n".join(plain(line) for line in compose(world, v, t, 92, 30))
            assert frame.state[0] in text  # the line under the grid fits the smallest screen
            frames[t] = frame
        set_view(world, "lanes")
        lane = adapter_for(world).frame(v, 20.5, 100)
        return world, frames, lane

    world, given, lane = pictures("main")
    run = world.runs["main"]
    kills = run.rows("kills", 0, 60)
    # A kill turns the service red, and the door shuts while the pod restarts.
    t = kills[0][0] + 0.1
    assert adapter_for(world).frame("main", t, 100).closed
    set_view(world, "cluster")
    assert adapter_for(world).frame("main", t).nodes[0] == RED
    # The dual write publishes from the service (node 0) to the broker (node 4) ...
    flights = [f for fr in given.values() for f in fr.flights]
    assert any(src == 0 and dest == 4 for src, dest, _, _ in flights)
    world, solved, _ = pictures("reference")
    flights = [f for fr in solved.values() for f in fr.flights]
    # ... the outbox publishes from the relay (node 2), and shipping never ships twice.
    assert any(src == 2 and dest == 4 for src, dest, _, _ in flights)
    assert not any(src == 0 and dest == 4 for src, dest, _, _ in flights)
    assert not any(colour in (RED, EXTRA3) for _, dest, _, colour in flights if dest == 3)

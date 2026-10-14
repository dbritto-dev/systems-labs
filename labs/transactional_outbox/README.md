# Lab: transactional outbox

*[Leer en español](es/README.md)*

Customers place ~50 orders a second through your `OrderService.place_order(order)`. Every saved
order must reach shipping as an OrderPlaced event on the broker, exactly once in effect: shipping
(your `ShippingConsumer.handle(event)`) creates one shipment per order. The order service's pod
also runs your `Relay`; shipping is another service that reads the topic in order and commits its
offset every second.

At random times, like in production, the order service's pod is killed again and again (an OOM
kill, a deploy without a graceful shutdown, a lost node: open transactions roll back, the relay
dies too, the pod is back after 1 s), the broker is down (a lost leader, an expired certificate,
a full disk), a share of the order commits fail (deadlocks, lock timeouts, a failover), the relay
alone keeps being killed, or shipping's consumer group keeps rebalancing (it goes back to its last
committed offset, on a fresh `ShippingConsumer`). A kill strikes between two steps of the work:
right after a publish was acknowledged, or right after a commit. The run never restarts. The first
incident is always a crash loop at 0:20–0:30.

```
uv run python -m live transactional_outbox          # watch it; edit main.py and save
uv run python -m live transactional_outbox --lesson # the concept, links and a checklist
uv run pytest labs/transactional_outbox             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Dual write (given) | save the order and publish the event in the request's transaction; shrug if the broker is down | a kill after a publish leaves a phantom (an event for an order that rolled back, red); a broker outage loses every event of the orders saved during it |
| 1 Transactional outbox | `tx.insert("outbox", event)` in the order's transaction, no publish; `Relay.relay_once`: `fetch_unsent`, publish each, `mark_sent` | nothing lost, nothing invented; the outbox fills while the broker is down and drains after; but a kill between publish and mark, or a rebalance, ships some orders twice (deep orange) |
| 2 Idempotent consumer | in `handle`'s transaction, skip an event id found in "processed", else record it with the shipment | repeats still arrive and are skipped (grey); every goal OK |

Goals, judged per incident: baseline ok (before: ≥ 99% of the saved orders reached shipping),
lost events = 0 (saved during it, never reached shipping, 15 s to arrive), phantom events = 0
(published for an order that was never saved), shipped twice = 0 (during and 5 s after), and lag
p99 < 3 s (from saving an order to shipping seeing it, for orders saved in the 10 s after).

The cluster picture opens first: the service, its database and the relay on top, shipping and the
broker below. The lanes picture shows the orders at the order service's door, the outbox backlog
as the server's gauge. Press `v` to switch.

- **Why not save, commit, then publish?** It only moves the gap. A kill after the commit and
  before the publish loses the event (the lab tries it: right after a commit). There is no order
  of two writes to two systems that survives a crash between them.
- **Why publish before marking sent?** Mark first and a kill in between loses the event forever.
  Publish first and the worst case is a duplicate, which the consumer can drop. That is why
  shipping must be idempotent: at-least-once delivery is the best a relay can promise.
- **Why in the same transaction at shipping?** Record the event id in another transaction and a
  failure between the two either skips a shipment or ships twice. A set in memory is lost when
  a rebalance hands the topic to a fresh consumer.
- **Why the lag goal?** A relay that naps or publishes a few rows per round cannot drain the
  backlog of a broker outage: the events are not lost, but they arrive late. Publish in batches.

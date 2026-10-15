"""Lab transactional_outbox, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Transactional outbox"
SUMMARY = "Save each order and announce it to shipping: never lose an event, invent one, or ship twice."
PARAMS = {"rate": "orders per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"crash": "KILLED", "broker": "DOWN", "locks": "LOCKS", "relay": "RELAY", "rebalance": "REBAL",
         "calm": "CALM"}
CAUSES = {
    "oom_kill": "a memory leak gets the order service OOM-killed",
    "deploy_kill": "a deploy kills pods without a graceful shutdown",
    "node_lost": "the node running the order service is lost",
    "spot_reclaim": "the cloud reclaims the spot instances",
    "leader_lost": "a broker dies and its partitions have no leader",
    "rolling_upgrade": "a rolling upgrade of the brokers goes wrong",
    "cert_expired": "the broker's TLS certificate has expired",
    "disk_full": "the broker's disk is full and it refuses writes",
    "migration_lock": "a migration holds locks: commits time out",
    "batch_deadlock": "a nightly batch job deadlocks with the orders",
    "db_failover": "the orders database fails over mid-commit",
    "hot_row": "a flash sale hammers one stock row: serialization failures",
    "relay_oom": "the relay is OOM-killed on a huge batch",
    "relay_deploy": "a deploy restarts the relay again and again",
    "lease_lost": "the relay keeps losing its leader lease",
    "consumer_deploy": "shipping deploys: its consumer group rebalances",
    "autoscale": "autoscaling adds and removes shipping consumers",
    "missed_heartbeat": "a slow shipping consumer misses heartbeats and is kicked out",
}

STAGES = [
    StageText("Dual write",
              "Challenge: a kill between the database and the broker loses events or invents them.",
              "Stage 1: write the event to the outbox in the order's transaction"),
    StageText("Transactional outbox",
              "Challenge: after a kill the relay publishes again, and orders ship twice. Dedupe them.",
              "Stage 2: record each event id in the shipment's transaction"),
    StageText("Idempotent consumer",
              "Solved: every saved order is shipped exactly once, and nothing else is.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "ship every saved order"),
    "lost": GoalText("Lost events = 0", "write the event in the tx"),
    "phantom": GoalText("Phantom events = 0", "publish only from the relay"),
    "dup": GoalText("Shipped twice = 0", "dedupe by event id"),
    "lag": GoalText("Lag p99 < 3s after", "relay in batches, no naps"),
}

LEGEND = {"idle": "idle", "event": "order, event", "republished": "published again",
          "twice": "shipped twice", "bad": "lost or phantom", "shipped": "shipped", "skipped": "deduped",
          "limit": "order rate", "incident": "incident"}

STRINGS = {
    # incidents
    "crash_start": "the order service is killed every {every:.1f} s: {cause}",
    "crash_end": "the order service stays up again",
    "broker_start": "the broker refuses every message: {cause}",
    "broker_end": "the broker is back",
    "locks_start": "{share:.0%} of the order commits fail: {cause}",
    "locks_end": "commits go through again",
    "relay_start": "the relay is killed every {every:.1f} s: {cause}",
    "relay_end": "the relay stays up again",
    "rebalance_start": "shipping rebalances every {every:.1f} s: {cause}",
    "rebalance_end": "shipping's consumer group is stable again",
    "warn_lost": "{n} saved orders never reached shipping",
    "warn_twice": "{n} orders shipped twice",
    # goal values
    "count": "{n}",
    "on_the_way": "{n} on the way",
    # the panel
    "tile_lost": "Lost",
    "tile_phantom": "Phantom",
    "tile_twice": "Twice",
    "bar_saved": "Saved",
    "bar_published": "Published",
    "bar_shipped": "Shipped",
    "limit": "orders/s",
    "head_phantom": "{n} phantom events in 10 s",
    "head_lost": "{n} events lost in 10 s",
    "head_twice": "{n} orders shipped twice in 10 s",
    "head_outbox": "{n} events wait in the outbox",
    "head_ok": "Every saved order shipped once",
    # the pictures
    "state_restart": "RESTARTING",
    "state_broker": "BROKER DOWN",
    "state_relay": "RELAY DOWN",
    "state_rebalance": "REBALANCING",
    "state_locks": "DEADLOCKS",
    "lane_state": "{state} · outbox {n}",
    "pic_state": "service·db·relay / shipping·broker: {state}",
    # the pipeline picture: a name under each box
    "box_service": "service",
    "box_service_short": "svc",
    "box_service_tiny": "S",
    "box_db": "db",
    "box_db_n": "db {n}",
    "box_relay": "relay",
    "box_relay_short": "relay",
    "box_relay_tiny": "R",
    "box_broker": "broker",
    "box_broker_short": "brkr",
    "box_broker_tiny": "B",
    "box_shipping": "shipping",
    "box_shipping_short": "ship",
    "box_shipping_tiny": "sh",
    "note": "Dots are a sample of orders and events, slowed down (cosmetic).",
    "subtitle": "per second, last 1 s",
    "title": "Events",
    # errors in your code
    "stuck": "an order has been running for over {seconds:.0f} s: does place_order() ever return?",
}

LESSON = Lesson(
    title="Transactional outbox",
    one_liner="Writing to a database and a broker is two writes with no transaction between them. "
              "Make it one write, then publish from it, and let the consumer drop repeats.",
    learn=(
        "A dual write saves the order and publishes the event to two systems. There is no transaction "
        "across them, so any failure in between splits them: the process is killed after the commit "
        "(the event is lost), the broker is down (the event is lost), or the event goes out before a "
        "commit that then fails (a phantom: shipping ships an order that does not exist).",
        "The transactional outbox writes the event as a row in an outbox table, in the same database "
        "transaction as the order. Either both are saved or neither is. A separate relay reads unsent "
        "rows, publishes them, and marks them sent. This is the only path to the broker.",
        "The relay publishes first and marks after. If it dies in between, the row is published again "
        "after the restart: at-least-once delivery. Marking first would be at-most-once, and lose events. "
        "Consumer group rebalances redeliver too. Duplicates are normal; plan for them.",
        "An idempotent consumer records the id of every event it has handled in its own database, in the "
        "same transaction as the effect (the shipment), and skips an id it has seen. At-least-once "
        "delivery plus an idempotent consumer is exactly-once in effect.",
        "Lag is the price: an event leaves when the relay next polls. Poll often, publish in batches, "
        "and after a broker outage drain the backlog quickly. Change data capture (Debezium reading the "
        "database log) is a relay that does not poll.",
    ),
    watch_for=(
        "Dual write: each kill right after a publish leaves a phantom (red); a broker outage loses every "
        "event of the orders saved during it.",
        "Transactional outbox: nothing is lost or invented, the outbox backs up while the broker is down "
        "and drains after; but kills and rebalances ship some orders twice (deep orange).",
        "Idempotent consumer: repeats still arrive (grey at shipping), and are skipped.",
    ),
    build=(
        ("PostgreSQL: the order and its event in one transaction",
         "BEGIN;\n"
         "INSERT INTO orders (id, customer, total) VALUES ($1, $2, $3);\n"
         "INSERT INTO outbox (id, topic, payload) VALUES ($4, 'orders', $5);\n"
         "COMMIT;"),
        ("The relay: publish, then mark (SKIP LOCKED lets several relays share the table)",
         "rows = SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED;\n"
         "for row in rows: producer.send(row.topic, key=row.aggregate_id, value=row.payload)\n"
         "producer.flush()\n"
         "UPDATE outbox SET sent_at = now() WHERE id = ANY($ids);"),
        ("The consumer: dedupe in the same transaction as the effect",
         "BEGIN;\n"
         "INSERT INTO processed_events (event_id) VALUES ($1) ON CONFLICT DO NOTHING;\n"
         "-- no row inserted: seen it, COMMIT and skip\n"
         "INSERT INTO shipments (order_id) VALUES ($2);\n"
         "COMMIT;"),
    ),
    checklist=(
        "Never publish from inside a request that also writes the database: write an outbox row instead.",
        "The outbox row and the business row commit in one transaction.",
        "The relay publishes, waits for the broker's acknowledgement, then marks rows sent.",
        "Every event has a unique id, and consumers dedupe on it in the same transaction as their effect.",
        "Keep processed ids at least as long as redeliveries can happen; delete sent outbox rows.",
        "Alert on outbox backlog and on the age of the oldest unsent row.",
        "Publish with the aggregate id as the key, so one order's events stay in order.",
    ),
    refs=(
        Ref("microservices.io: Transactional outbox",
            "https://microservices.io/patterns/data/transactional-outbox.html",
            "The pattern, its forces, and the relay (polling publisher or log tailing)."),
        Ref("microservices.io: Idempotent consumer",
            "https://microservices.io/patterns/communication-style/idempotent-consumer.html",
            "Recording processed message ids so duplicates are harmless."),
        Ref("Confluent: Understanding the dual write problem",
            "https://www.confluent.io/blog/dual-write-problem/",
            "Why writing to a database and Kafka without a transaction loses or invents data."),
        Ref("AWS Prescriptive Guidance: Transactional outbox pattern",
            "https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html",
            "The outbox on AWS, with duplicate handling on the consumer side."),
        Ref("Debezium: Outbox event router",
            "https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html",
            "A relay built on change data capture: it tails the database log instead of polling."),
        Ref("Confluent: Message delivery guarantees",
            "https://docs.confluent.io/kafka/design/delivery-semantics.html",
            "At-most-once, at-least-once and exactly-once, and where each comes from."),
    ),
    try_next=(
        "Do stage 1 in labs/transactional_outbox/main.py and watch the Lost and Phantom tiles stay at 0.",
        "Then watch the next crash: why does shipping get some orders twice now?",
        "Do stage 2 and watch the repeats turn grey: skipped, never shipped twice.",
    ),
)

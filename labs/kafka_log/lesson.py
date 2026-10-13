from core.lessons import Lesson, Ref

LESSON = Lesson(
    title="Kafka log (Gossip Glomers #5)",
    one_liner="A replicated append-only log: every message gets a unique offset, and no reader ever skips one.",
    learn=(
        "A log per key: each message gets an offset, offsets only grow, and readers (consumers) poll "
        "from an offset on and commit how far they got. Kafka, Redpanda and Pulsar all work this way.",
        "With two nodes, each one counting offsets on its own hands the same offset to two different "
        "messages, and a reader on one node never sees the other node's messages.",
        "A linearizable store (lin-kv) fixes correctness: a counter per key bumped with compare-and-swap "
        "gives unique offsets. But every send now costs several round trips, and concurrent sends to one "
        "hot key fight over the counter: CAS failures, retries, and latency that explodes.",
        "Partitioning ownership removes the contention: one node owns each key and assigns its offsets in "
        "memory; the other node forwards to it. One message per operation, no storage round trips. This is "
        "how Kafka itself works (a leader per partition).",
    ),
    watch_for=(
        "Single node: red flashes and DUPLICATE OFFSET / LOST WRITE under the nodes.",
        "Multi-node: no anomalies, but orange lin-kv messages everywhere; in a burst the p99 send soars.",
        "Efficient: a few blue messages between the nodes, and sends stay fast through bursts.",
        "lin-kv slowing down hurts every design that waits on it on the hot path.",
    ),
    build=(
        ("Maelstrom: run the real challenge against your own binary",
         "./maelstrom test -w kafka --bin ./my-kafka --node-count 2 \\\n"
         "    --concurrency 2n --time-limit 20 --rate 1000"),
        ("Kafka: the owner of a partition is its leader",
         "kafka-topics --create --topic orders --partitions 12 --replication-factor 3\n"
         "# each partition has one leader broker that assigns offsets; producers send to it"),
    ),
    checklist=(
        "Decide who assigns order: one owner (leader) per key beats a shared counter under contention.",
        "Never acknowledge an offset before the message is stored where readers will find it.",
        "A poll may return fewer messages, never a gap below what it returns.",
        "Committed offsets only move forward; store them where every node can read them.",
        "Count the round trips on the hot path, and test with one hot key.",
    ),
    refs=(
        Ref("Fly.io: Gossip Glomers #5a Single-Node Kafka-Style Log", "https://fly.io/dist-sys/5a/",
            "The original challenge."),
        Ref("Fly.io: #5b Multi-Node Kafka-Style Log", "https://fly.io/dist-sys/5b/",
            "Two nodes and lin-kv: correctness first."),
        Ref("Fly.io: #5c Efficient Kafka-Style Log", "https://fly.io/dist-sys/5c/",
            "Fewer CAS failures and messages per operation."),
        Ref("Maelstrom: the kafka workload", "https://github.com/jepsen-io/maelstrom/blob/main/doc/workloads.md",
            "The messages and the anomalies its checker looks for."),
        Ref("Apache Kafka: design", "https://kafka.apache.org/documentation/#design",
            "Partitions, leaders, offsets and consumer positions."),
        Ref("Jepsen: Redpanda 21.10.1", "https://jepsen.io/analyses/redpanda-21.10.1",
            "Real lost and duplicated writes in a Kafka-compatible log, and how they were found."),
    ),
    try_next=(
        "Do stage 1 in labs/kafka_log/main.py with lin-kv and watch the anomalies stop.",
        "Then watch a hot-key burst: how many CAS retries does one send take?",
        "Try --set rate=60: does your stage-2 design still cost about one message per operation?",
    ),
)

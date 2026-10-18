"""Lab kafka_style_log, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Kafka log (Gossip Glomers #5)"
SUMMARY = "Gossip Glomers #5: a replicated Kafka-style log on two nodes; correct first, then cheap."
PARAMS = {"rate": "client operations per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"burst": "BURST", "calm": "CALM", "slow": "SLOW", "fast": "FAST"}
CAUSES = {
    "replay": "a producer replayed a day of events into one topic",
    "flash_sale": "a flash sale sent every order to one topic",
    "retry_storm": "a retry storm upstream hammered one topic",
    "compaction": "lin-kv is compacting its storage",
    "noisy_disk": "a noisy neighbour is starving lin-kv's disk",
    "lost_replica": "lin-kv lost a replica and is catching up",
}

STAGES = [
    StageText("Single node",
              "Challenge: each node hands out its own offsets, so two messages share one. Agree on them.",
              "Stage 1 (5b): keep offsets and messages in lin-kv"),
    StageText("Multi-node",
              "Challenge: correct, but every send costs ~10 messages and stalls on one hot key.",
              "Stage 2 (5c): fewer round trips, e.g. an owner per key"),
    StageText("Efficient",
              "Solved: offsets are unique, nothing is lost, and a send costs about one message.",
              "All stages done"),
]

GOALS = {
    "unique": GoalText("Offsets rise", "agree on offsets"),
    "lost_writes": GoalText("No lost writes", "never skip an offset"),
    "commits": GoalText("Commits kept", "share committed offsets"),
    "msgs": GoalText("Msgs/op < 3", "fewer lin-kv round trips"),
    "p99": GoalText("p99 send < 100ms", "an owner per key"),
}

LEGEND = {"node": "node", "lin_kv": "lin-kv", "duplicate": "duplicate", "backwards": "offset back", "lost_write": "lost write",
          "lost_commit": "lost commit", "client_request": "client request",
          "node_message": "node message", "kv_message": "lin-kv message", "limit": "limit"}

STRINGS = {
    # incidents
    "title_burst": "Hot key",
    "title_slowkv": "Slow lin-kv",
    "burst_start": "{severity:.1f}x traffic, mostly sends to one key: {cause}",
    "burst_end": "traffic is back to normal",
    "slow_start": "lin-kv answers {severity:.0f}x slower: {cause}",
    "slow_end": "lin-kv is fast again",
    "warn_slow": "sends take over 300 ms",
    "one_key": "one key",
    # anomalies
    "duplicate": "duplicate offset",
    "lost_write": "lost write",
    "lost_commit": "lost commit",
    "backwards": "offset going back",
    # goal values
    "failed": "failed",
    # the panel
    "tile_msgs": "Msgs/op",
    "tile_p99": "p99",
    "tile_anomalies": "Anomalies",
    "traffic": "Traffic",
    "bar_clients": "Clients",
    "bar_messages": "Messages",
    "limit": "{limit:.0f} msgs/op",
    "chart_limit": "{limit:.0f}/op",
    "head_anomaly": "{what} on {k}!",
    "head_hot": "Hot {k}: p99 send {p99}",
    "head_slow": "lin-kv is slow: p99 send {p99}",
    "head_ok": "Log ok: {mpo} msgs per operation",
    "note_dots": "Dots slowed down to be seen (cosmetic).",
    # the picture
    "state_hot": "HOT KEY {k}",
    "state_kv_slow": "LIN-KV SLOW",
    # the lanes picture (the clients' view): states under the cluster, at most 13 letters
    "lanes_anomaly": "ANOMALY",
    "lanes_kv_slow": "KV SLOW",
    # the fan-in picture: the network (the door), the nodes, lin-kv (the store)
    "fan_network": "network",
}

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
        "Do stage 1 in labs/kafka_style_log/main.py with lin-kv and watch the anomalies stop.",
        "Then watch a hot-key burst: how many CAS retries does one send take?",
        "Try --set rate=60: does your stage-2 design still cost about one message per operation?",
    ),
)

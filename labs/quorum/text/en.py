"""Lab quorum, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Quorums"
SUMMARY = "Dynamo-style replication: every key on 3 of 5 nodes. Read the latest write while a node is down."
PARAMS = {"rate": "client operations per second (half put, half get)"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"crash": "CRASH", "cut": "CUT", "slow": "SLOW", "back": "BACK", "fast": "FAST"}
CAUSES = {
    "oom_kill": "the kernel killed it for using too much memory",
    "kernel_panic": "a kernel panic after a driver update",
    "bad_deploy": "a bad deploy crashed it on start",
    "switch_port": "its switch port went down",
    "firewall_rule": "a firewall rule blocked the cluster port",
    "dns": "a DNS change sent its peers to the wrong address",
    "gc_pause": "long garbage-collection pauses",
    "disk_full": "its disk is almost full and every write crawls",
    "noisy_neighbour": "a noisy neighbour is starving its CPU",
}

STAGES = [
    StageText("One copy",
              "Challenge: each node keeps its own copy, so reads miss the latest write. Use quorums.",
              "Stage 1: write to W=2 of 3 replicas, read from R=2"),
    StageText("Quorums",
              "Challenge: a node that was down comes back with old data. Bring it up to date.",
              "Stage 2: hinted handoff and read repair"),
    StageText("Quorums + repair",
              "Solved: reads always see the latest write, and replicas catch up after a failure.",
              "All stages done"),
]

GOALS = {
    "stale": GoalText("Stale reads = 0", "use quorums: W + R > N"),
    "answered": GoalText("Answered ≥ 99%", "wait for W or R, not all"),
    "sync": GoalText("In sync ≥ 99%", "hinted handoff"),
    "msgs": GoalText("Msgs/op < 10", "send fewer messages"),
}

LEGEND = {"in_sync": "in sync", "behind": "behind", "down": "down", "request": "client request",
          "message": "message", "dropped": "dropped", "limit": "limit"}

STRINGS = {
    # incidents
    "crashed": "{node} crashed: {cause}",
    "cut_off": "{node} is cut off: {cause}",
    "slowed": "{node} is slow: {cause}",
    "back": "{node} is back",
    "fast": "{node} is fast again",
    "warn_stale": "{n} reads missed the latest write",
    # the panel
    "tile_stale": "Stale",
    "tile_answered": "Served",
    "tile_sync": "In sync",
    "bar_clients": "Clients",
    "bar_nodes": "Nodes",
    "messages": "Messages",
    "limit": "10 msgs/op",
    "chart_limit": "10/op",
    "head_down": "{node} down: {n} keys behind on it",
    "head_slow": "{node} slow: quorums skip it",
    "head_sync": "{share:.0%} of keys in sync",
    "head_ok": "Every key in sync on 3 replicas",
    "head_stale": "{n} stale reads in the last 10 s",
    "note_chart": "Chart: messages between nodes per second.",
    # the picture
    "state_sick": "{state}: {node}",
    # errors in your code
    "no_store": "QuorumNode must keep its data in self.store",
}

LESSON = Lesson(
    title="Quorums",
    one_liner="Keep every key on N nodes, write to W, read from R: with W + R > N, reads see the last write.",
    learn=(
        "Leaderless replication (Amazon Dynamo, Cassandra, Riak): any node can take a request and "
        "coordinate it. It sends a write to the key's N replicas and answers after W acknowledged it; "
        "a read asks the replicas and answers from the newest of R replies.",
        "When W + R > N, every read quorum overlaps every write quorum in at least one node, so a read "
        "always meets the last acknowledged write. With N=3, W=2, R=2 one node can be down and nobody "
        "notices.",
        "Versions decide which reply is newest: here a timestamp plus the node id. Real systems use "
        "vector clocks or hybrid logical clocks, because real clocks drift.",
        "Quorums keep reads right, but a node that was down still holds old data. Read repair fixes a "
        "stale replica when a read sees it; hinted handoff keeps the writes a replica missed and hands "
        "them over when it is back; anti-entropy (Merkle trees) compares replicas in the background.",
    ),
    watch_for=(
        "One copy: reads land on a node that never saw the write; the Stale tile turns red.",
        "Quorums: no stale reads, even with a node down; but after it comes back, In sync stays below 99%.",
        "Read repair alone only fixes the keys someone reads: most keys stay behind for a long time.",
        "Quorums + repair: hints flow to the node as soon as it is back, and In sync returns to 100%.",
    ),
    build=(
        ("Apache Cassandra: the consistency level per request",
         "CONSISTENCY QUORUM;   -- in cqlsh, before SELECT * FROM orders WHERE id = ?;"),
        ("Riak: N, R and W per bucket",
         "curl -XPUT http://riak:8098/buckets/orders/props \\\n"
         "     -H 'Content-Type: application/json' -d '{\"props\": {\"n_val\": 3, \"r\": 2, \"w\": 2}}'"),
        ("Wait for the first W of N replies (asyncio)",
         "acks = 0\n"
         "for done in asyncio.as_completed(tasks):\n"
         "    acks += await done\n"
         "    if acks >= W:\n"
         "        return True"),
    ),
    checklist=(
        "Pick N, W and R per data set: W + R > N for reads that see the last write.",
        "Know what happens when fewer than W replicas answer: fail, or a sloppy quorum with hints.",
        "Version every value (vector clocks or HLCs) and decide how to resolve conflicts.",
        "Run read repair and anti-entropy, and alert on replicas that stay behind.",
        "Test with a node down and with a slow node: latency should follow the W-th fastest replica.",
    ),
    refs=(
        Ref("Amazon Dynamo (SOSP 2007)",
            "https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf",
            "Quorums, sloppy quorums, hinted handoff, vector clocks and Merkle-tree anti-entropy."),
        Ref("Apache Cassandra: how data is distributed and replicated",
            "https://cassandra.apache.org/doc/latest/cassandra/architecture/dynamo.html",
            "Replication, tunable consistency, hinted handoff and read repair in Cassandra."),
        Ref("Riak KV: replication properties",
            "https://docs.riak.com/riak/kv/latest/developing/app-guide/replication-properties/index.html",
            "N, R and W per bucket, and what they buy you."),
        Ref("Jepsen: consistency models",
            "https://jepsen.io/consistency",
            "What 'reads see the latest write' means, precisely."),
    ),
    try_next=(
        "Do stage 1 in labs/quorum/main.py and watch the Stale tile go to zero.",
        "Then wait for a crash: what happens to In sync after the node is back?",
        "Do stage 2 and watch the hints flow to the node that came back.",
    ),
)

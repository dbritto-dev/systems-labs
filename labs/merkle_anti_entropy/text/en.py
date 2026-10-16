"""Lab merkle_anti_entropy, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Merkle anti-entropy"
SUMMARY = "4 replicas of 20,000 keys drift apart silently: find and repair the differences, cheaply."
PARAMS = {"rate": "client writes per second (reads are twice as many)"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"down": "DOWN", "up": "UP", "blip": "BLIP", "heal": "HEAL", "disk": "DISK", "restore": "BACKUP"}
CAUSES = {
    "kernel_panic": "a kernel panic after a driver update",
    "oom_kill": "the OOM killer stopped the database process",
    "host_reboot": "its host was rebooted for a security patch",
    "switch_failover": "a top-of-rack switch failed over",
    "nic_reset": "its network card reset under load",
    "conntrack": "the firewall's connection table filled up",
    "bit_rot": "bit rot: checksums failed and the keys were dropped",
    "bad_sector": "bad sectors on an aging disk",
    "raid_rebuild": "a RAID rebuild lost a stripe",
    "wrong_snapshot": "the wrong snapshot was restored after a migration",
    "operator_error": "an operator restored last week's backup by mistake",
    "rollback": "a rollback script restored an old data file",
}

STAGES = [
    StageText("No repair",
              "Challenge: missed writes are never repaired; reads disagree by replica. Repair them.",
              "Stage 1: a full scan: compare every key with a peer"),
    StageText("Full scan",
              "Challenge: replicas converge, but every round sends all 20,000 keys. Send only diffs.",
              "Stage 2: Merkle trees: descend where hashes differ"),
    StageText("Merkle trees",
              "Solved: differences found by hashes and repaired in seconds, for a few entries a key.",
              "All stages done"),
]

GOALS = {
    "fixed": GoalText("Fixed ≤ 15 s", "anti-entropy rounds"),
    "stale": GoalText("Stale ≤ 0.2%", "repair every key in time"),
    "sent": GoalText("Sent ≤ 150/key", "a Merkle tree, small leaves"),
    "hashes": GoalText("Hash ≤ 10k/s", "update the tree on write"),
}

LEGEND = {"in_sync": "in sync", "diverged": "missing writes", "down": "down", "request": "client request",
          "replication": "replication", "repair": "repair", "dropped": "dropped"}

STRINGS = {
    # goals
    "left": "{n:,} left",
    "per_key": "{v:.0f}/key",
    "none_fixed": "{n:,} for 0",
    "rate": "{v:,.0f}/s",
    # incidents
    "down": "{node} is down: {cause}; the others keep {hints} hints each for it",
    "up": "{node} is back; the hints are replayed",
    "blip": "a network blip cut {node} off: {cause}; replication batches are lost",
    "healed": "{node} is reachable again",
    "disk": "a bad disk lost {n:,} keys on {node}: {cause}",
    "restore": "an old backup of {first}…{last} ({n:,} keys) is back on {node}: {cause}",
    "warn_hints": "{n:,} writes to {node} overflowed its hints: never sent",
    "warn_diverged": "{n:,} keys differ after it",
    # the panel
    "tile_diverged": "Diverged",
    "tile_stale": "Stale reads",
    "tile_sent": "Sent/key",
    "limit": "10k/s",
    "hash_title": "Hash work",
    "hash_sub": "per replica, last 1 s",
    "head_down": "{node} down: hints pile up",
    "head_blip": "{node} cut off: batches lost",
    "head_diverged": "{n:,} keys differ, most on {node}",
    "head_repaired": "{n:,} keys repaired in 1 s",
    "head_ok": "Every replica holds the latest",
    "stat_reads": "reads",
    "stat_writes": "writes",
    "stat_stale": "stale",
    "stat_diverged": "diverged",
    "stat_repair": "repair sent",
    "note_chart": "Chart: entries sent per second: replication, repair.",
    # the picture
    "state_down": "{node} DOWN",
    "state_diverged": "{n:,} KEYS DIFFER",
    "state_sync": "IN SYNC",
    # the lanes picture (the clients' view): states under the server, at most 13 letters
    "lanes_stale": "STALE READS",
    "lanes_diverged": "DIVERGED",
    "lanes_sync": "IN SYNC",
    # the peers picture: under each replica, what it misses, short
    "peer_down": "{node} down",
    "peer_cut": "{node} cut off",
    "peer_missing": "{node} −{n}",
    # errors in your code
    "not_replica": "ReplicaNode must subclass Replica (from labs.merkle_anti_entropy.api)",
}

LESSON = Lesson(
    title="Merkle anti-entropy",
    one_liner="Replicas drift apart silently; compare hash trees to find the few keys that differ, not every key.",
    learn=(
        "Replication misses writes now and then, and nothing tells you: a replica down longer than "
        "its hint window, a network blip that drops a batch, a bad disk, an old backup restored by "
        "mistake. Without repair, those replicas stay wrong forever, and reads disagree depending "
        "on which replica answers.",
        "Anti-entropy is a background process that compares replicas and copies the newer version "
        "of every key that differs. The simplest one, a full scan, sends every key's version to a "
        "peer: it repairs everything, but its cost grows with the data, not with the differences.",
        "A Merkle tree hashes the key range: each leaf covers a few keys, each inner node is the "
        "hash of its children, and the root sums up everything. Two replicas compare roots; if they "
        "differ, they compare the children and descend only where hashes differ, then exchange the "
        "keys of the leaves that differ (Dynamo, Cassandra, Riak).",
        "Keep the tree up to date on every write (a few hashes up one path), instead of rebuilding "
        "it from all the data each round. Choose the leaf size: big leaves send many good keys "
        "along with each bad one; tiny leaves make a deep tree with more hashes to exchange.",
    ),
    watch_for=(
        "No repair: after an incident a replica stays orange forever, and some reads come back stale.",
        "Full scan: the replicas turn blue again, but the chart is a wall of repair traffic every round.",
        "Merkle trees: a calm round costs a few hundred entries; after an incident, a short burst repairs it.",
        "Leaves too big, or a tree rebuilt every round: Sent/key or Hash work goes over its limit.",
    ),
    build=(
        ("Cassandra: repair a table (Merkle trees per token range)",
         "nodetool repair --full my_keyspace my_table\n"
         "nodetool repair -pr my_keyspace          # only this node's primary ranges"),
        ("Riak: active anti-entropy, hash trees kept up to date on write",
         "riak.conf:\n"
         "  anti_entropy = active\n"
         "  anti_entropy.tree.build_limit.per_timespan = 1h"),
        ("A Merkle descent: only the children whose hashes differ",
         "nodes = [root]\n"
         "while level < depth:\n"
         "    differ = await peer.compare(level, {i: tree.hash(level, i) for i in nodes})\n"
         "    nodes = [c for i in differ for c in tree.children(i)]"),
    ),
    checklist=(
        "Assume replicas drift: run anti-entropy all the time, not only after known incidents.",
        "Make its cost grow with the differences, not with the data: compare hashes first.",
        "Keep the hash trees incremental, and throttle repair so it never hurts serving traffic.",
        "Pick leaves of a few keys to a few hundred, so one bad key does not stream a whole range.",
        "Alert on repair volume: a sudden burst means something lost writes.",
    ),
    refs=(
        Ref("Amazon Dynamo (SOSP 2007)",
            "https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf",
            "Sections 4.6 and 4.7: hinted handoff, and replica synchronization with Merkle trees."),
        Ref("Apache Cassandra: repair",
            "https://cassandra.apache.org/doc/latest/cassandra/managing/operating/repair.html",
            "Full and incremental repair, and how Merkle trees are built and compared."),
        Ref("Apache Cassandra: hints",
            "https://cassandra.apache.org/doc/latest/cassandra/managing/operating/hints.html",
            "Hinted handoff, its window, and why repair is still needed after it."),
        Ref("Riak KV: active anti-entropy",
            "https://docs.riak.com/riak/kv/latest/learn/concepts/active-anti-entropy/index.html",
            "Hash trees updated in real time, compared continuously between replicas."),
        Ref("ScyllaDB: row-level repair",
            "https://www.scylladb.com/2019/08/13/scylla-open-source-3-1-efficiently-maintaining-consistency-with-row-level-repair/",
            "Why big Merkle leaves stream far more data than the differences, and a fix."),
        Ref("Van Renesse et al.: efficient reconciliation for anti-entropy",
            "https://www.cs.cornell.edu/home/rvr/papers/flowgossip.pdf",
            "Anti-entropy protocols, what they send, and how to bound it."),
        Ref("Merkle tree (Wikipedia)",
            "https://en.wikipedia.org/wiki/Merkle_tree",
            "Hash trees: the idea, and where else they are used."),
    ),
    try_next=(
        "Do stage 1 in labs/merkle_anti_entropy/main.py and watch the replicas turn blue, and the chart.",
        "Then compare what a full scan sends with how many keys it repairs (Sent/key).",
        "Do stage 2; then try DEPTH = 1 and DEPTH = 4 and watch Sent/key and Hash work move.",
    ),
)

"""Lab txn, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Transactions (Gossip Glomers #6)"
SUMMARY = "Gossip Glomers #6: a replicated key/value store with transactions, totally available."
PARAMS = {"rate": "client transactions per second"}

INCIDENT = IncidentText("Partition", "the partition", "the next partition")
VERBS = {"split": "SPLIT", "heal": "HEAL"}
CAUSES = {
    "tor_switch": "a top-of-rack switch failed under one node",
    "firewall_port": "a firewall rule blocked the replication port on one node",
    "nic_drops": "one node's network card started dropping packets",
    "zone_link": "a cloud zone lost its link to the other two",
}

STAGES = [
    StageText("Single node",
              "Challenge: writes stay on the node that got them. Send them to the other nodes.",
              "Stage 1 (6b): replicate every write to the other nodes"),
    StageText("Replicated",
              "Challenge: writes made during a partition are lost for good. Re-send until acked.",
              "Stage 2 (6b): re-send until acked; the newest stamp wins"),
    StageText("Read uncommitted",
              "Challenge: readers see values a transaction overwrote itself. Replicate whole txns.",
              "Stage 3 (6c): replicate final values per txn, applied at once"),
    StageText("Read committed",
              "Solved: every node catches up through partitions, and no one sees intermediate values.",
              "All stages done"),
]

GOALS = {
    "fresh": GoalText("Fresh ≥ 95%", "replicate every write"),
    "answered": GoalText("Answered ≥ 99%", "never wait for a peer"),
    "caught_up": GoalText("Caught up ≥ 99%", "re-send until acked"),
    "g1b": GoalText("No G1b reads", "replicate whole txns"),
}

LEGEND = {"up_to_date": "up to date", "behind": "behind", "g1b_read": "G1b read", "transaction": "transaction",
          "replication": "replication", "dropped": "dropped", "partition": "partition"}

STRINGS = {
    # incidents
    "cut_off": "a node is cut off: {cause}",
    "whole_again": "the network is whole again",
    "warn_g1b": "n{node} showed an intermediate value of key {which}",
    # goal values
    "none": "none",
    "seen": "{n} seen",
    # the panel
    "tile_fresh": "Fresh",
    "tile_g1b": "G1b",
    "tile_answers": "Answers",
    "messages": "Messages",
    "bar_clients": "Clients",
    "bar_nodes": "Nodes",
    "head_g1b": "G1b: a reader saw an overwritten value",
    "head_cut": "n{node} is cut off: replication waits",
    "head_behind": "Some nodes are behind ({fresh:.1%} fresh)",
    "head_ok": "Every node is up to date",
    "note_chart": "Chart: replication messages/s.",
    # the picture
    "state_cut": "n{node} cut off",
    # errors in your code
    "no_store": "TxnNode must keep its key/value store in self.store (a dict)",
}

LESSON = Lesson(
    title="Transactions (Gossip Glomers #6)",
    one_liner="A replicated key/value store that answers every transaction, even cut off, and still never shows half-done work.",
    learn=(
        "Total availability: every node answers every transaction by itself, even during a partition. "
        "So nodes cannot coordinate before answering; they replicate afterwards and catch up later.",
        "Read uncommitted forbids only dirty writes (G0): two transactions' writes interleaving into "
        "a cycle. One stamp per transaction (time, node), and last-writer-wins by that stamp on every "
        "node, gives every key the same write order everywhere.",
        "Read committed also forbids aborted reads (G1a), intermediate reads (G1b) and cycles of "
        "information flow (G1c). An intermediate read sees a value a transaction overwrote itself: "
        "it leaks when writes travel one by one and a reader runs between them.",
        "The fix is to replicate whole transactions: only their final value per key, applied on the "
        "other node in one go.",
    ),
    watch_for=(
        "Single node: the nodes stay orange (behind): each only has its own clients' writes.",
        "Replicated: blue again, until a partition; afterwards some keys never catch up.",
        "Read uncommitted: everyone catches up, but red flashes: readers seeing intermediate values.",
        "Read committed: no red flashes, and every node catches up after each partition.",
    ),
    build=(
        ("Maelstrom: run the real challenge against your own binary",
         "./maelstrom test -w txn-rw-register --bin ./my-txn --node-count 2 --concurrency 2n \\\n"
         "    --time-limit 20 --rate 1000 --consistency-models read-committed \\\n"
         "    --availability total --nemesis partition"),
        ("Last writer wins, by one stamp per transaction",
         "stamp = (self.now(), self.rank, next(self.counter))\n"
         "for key, value in final_writes.items():\n"
         "    if stamp > self.stamps.get(key, ()):\n"
         "        self.store[key], self.stamps[key] = value, stamp"),
    ),
    checklist=(
        "Write down which anomalies your store forbids (G0, G1a, G1b, G1c...) and test for them.",
        "Replicate units of work (transactions), not single writes.",
        "Give every write a total order every replica agrees on (stamps, versions, or a log).",
        "Never drop replication on the floor: keep it until acknowledged.",
        "If you promise availability, never wait for another node before answering.",
    ),
    refs=(
        Ref("Fly.io: Gossip Glomers, challenge #6a Totally-Available Transactions",
            "https://fly.io/dist-sys/6a/",
            "The original challenge and its parts 6b and 6c."),
        Ref("Jepsen: Read Committed",
            "https://jepsen.io/consistency/models/read-committed",
            "What read committed forbids: G0, G1a, G1b, G1c."),
        Ref("Jepsen: Read Uncommitted",
            "https://jepsen.io/consistency/models/read-uncommitted",
            "The weakest model: no dirty writes (G0)."),
        Ref("Jepsen: G1b, intermediate read",
            "https://jepsen.io/consistency/phenomena/g1b",
            "The anomaly this lab's last stage removes, with examples (after Adya's definitions)."),
        Ref("Maelstrom: the txn-rw-register workload",
            "https://github.com/jepsen-io/maelstrom/blob/main/doc/workloads.md",
            "The txn message and its micro-operations."),
    ),
    try_next=(
        "Do stage 1 in labs/txn/main.py and watch the nodes turn blue.",
        "Then wait for a partition: which keys never catch up, and why?",
        "Do stage 3 and watch the red flashes stop.",
    ),
)

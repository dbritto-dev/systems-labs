from core.lessons import Lesson, Ref

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

from core.lessons import Lesson, Ref

LESSON = Lesson(
    title="Grow-only counter (Gossip Glomers #4)",
    one_liner="Count adds on stateless nodes through a key/value store that may answer with old values.",
    learn=(
        "Stateless nodes keep the truth in a shared store. Read-modify-write is not safe there: two "
        "nodes read the same value, both add, and the second write erases the first one's add. "
        "Nothing fails; the total just drifts low.",
        "Compare-and-swap (`cas old -> new`) fixes lost updates: the write only lands if nobody changed "
        "the value since you read it; otherwise you read again and retry. But on one hot key every add "
        "fights every other add, and a sequentially consistent store makes it worse: it may hand you an "
        "old value, so your cas fails even with no one else writing.",
        "Sequential consistency: every client sees the operations in one order, and its own writes, "
        "but not necessarily the latest ones of others. Reads can lag; they never go backwards.",
        "Partition the hot key: give each node a key only it writes, and read the sum. A grow-only "
        "counter is the simplest CRDT: per-node counts that only grow, merged by adding them up.",
    ),
    watch_for=(
        "In memory: every node reads a different, too-small total; seq-kv gets no requests.",
        "Shared key: the total grows, but slower than the adds; reads miss acknowledged adds.",
        "Compare-and-swap: red conflicts pile up, worst in a burst; adds start timing out.",
        "Key per node: no red at all; reads are right within the store's lag.",
    ),
    build=(
        ("Maelstrom: run the real challenge against your own binary",
         "./maelstrom test -w g-counter --bin ./my-counter --node-count 3 \\\n"
         "    --rate 100 --time-limit 20 --nemesis partition"),
        ("A compare-and-swap loop (and why it is not enough on a hot key)",
         "while True:\n"
         "    old = await kv.read(KEY)\n"
         "    try:\n"
         "        await kv.cas(KEY, old, old + delta, create=True)\n"
         "        break\n"
         "    except RPCError as e:\n"
         "        if e.code != 22: raise"),
        ("Redis: one hash field per node, sum on read",
         "await redis.hincrby('views', node_id, delta)\n"
         "total = sum(map(int, (await redis.hvals('views'))))"),
    ),
    checklist=(
        "Never read-modify-write shared state without a guard (cas, a transaction, or a single writer).",
        "Know your store's consistency: can a read return an old value? Can your own write vanish?",
        "Spread hot keys: one writer per key, merge on read (counters, sets, sharded totals).",
        "Count retries and conflicts; alert when a key is contended.",
        "Answer a client only once its update is durable.",
    ),
    refs=(
        Ref("Fly.io: Gossip Glomers, challenge #4 Grow-Only Counter",
            "https://fly.io/dist-sys/4/",
            "The original challenge."),
        Ref("Maelstrom: services (seq-kv, lin-kv)",
            "https://github.com/jepsen-io/maelstrom/blob/main/doc/services.md",
            "read, write and cas, and their consistency."),
        Ref("Jepsen: sequential consistency",
            "https://jepsen.io/consistency/models/sequential",
            "What a sequentially consistent store promises, and what it does not."),
        Ref("Shapiro et al.: A comprehensive study of CRDTs (2011)",
            "https://inria.hal.science/inria-00555588/document",
            "The G-Counter and its friends."),
    ),
    try_next=(
        "Do stage 1 in labs/g_counter/main.py and watch the 'Right' tile: why does it stay red?",
        "Do stage 2 and wait for a burst: what happens to the conflicts and to the adds?",
        "Try --set rate=40 on your stage 3: does anything get worse?",
    ),
)

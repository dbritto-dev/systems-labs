from core.lessons import Lesson, Ref

LESSON = Lesson(
    title="Unique IDs (Gossip Glomers #1-2)",
    one_liner="Hand out ids that no other request ever got, from any node, without asking anyone.",
    learn=(
        "Echo is the hello world of a node: receive a message, reply to the sender with in_reply_to set.",
        "Unique ids without coordination: combine something unique about the node (its id) with something "
        "unique on the node (a counter). No messages, so a partition cannot stop it.",
        "Asking a leader or a shared counter for the next number is unique too, but it stops working when "
        "the network splits: that is the availability you give up for coordination.",
        "A database key wants more: a 64-bit integer that grows with time, so new rows go at the end of the "
        "index. Snowflake packs milliseconds | node | sequence into 63 bits.",
        "Clocks jump backwards (NTP, VM pauses, migrations). A generator that trusts the clock then hands "
        "out smaller ids, and can repeat old ones. Keep the last timestamp you used, and never go below it.",
    ),
    watch_for=(
        "Nothing yet: every request comes back red.",
        "A counter per node: replies go green, but the Dups tile climbs: n0 and n1 both hand out 1, 2, 3...",
        "Asking a leader: unique, until a partition cuts nodes off from it and their requests time out.",
        "Node + counter: always unique and available, but a string, and not ordered by time.",
        "Snowflake without a guard: when a clock steps back (an orange node), its ids go backwards.",
    ),
    build=(
        ("Snowflake ids, with a guard for clocks that step back",
         "ms = max(wall_ms() - EPOCH_MS, last_ms)\n"
         "seq = seq + 1 if ms == last_ms else 0\n"
         "if seq > 4095:            # used up this millisecond\n"
         "    ms, seq = ms + 1, 0\n"
         "last_ms = ms\n"
         "return (ms << 22) | (node << 12) | seq"),
        ("Or UUIDv7 (RFC 9562): 48-bit milliseconds then random bits, 128 bits",
         "uuid7 = time_ms(48) | version(4) | random(74)   # sortable, no node numbers to assign"),
    ),
    checklist=(
        "Ids come from the node itself: no network call on the hot path.",
        "Something unique per node (an assigned number), plus a per-node sequence.",
        "Milliseconds first if you need them sorted; a custom epoch to make 41 bits last ~69 years.",
        "Never let the timestamp go backwards; alert when the clock does.",
        "Plan the node numbers: 10 bits is 1024 generators, assigned once and never reused.",
    ),
    refs=(
        Ref("Fly.io: Gossip Glomers #1 Echo", "https://fly.io/dist-sys/1/", "The first challenge."),
        Ref("Fly.io: Gossip Glomers #2 Unique ID Generation", "https://fly.io/dist-sys/2/",
            "Unique ids that stay available through partitions."),
        Ref("Twitter's Snowflake (2010 source)", "https://github.com/twitter-archive/snowflake/tree/snowflake-2010",
            "The original timestamp | worker | sequence generator, and how it handles clocks going back."),
        Ref("RFC 9562: UUIDs, including UUIDv7", "https://www.rfc-editor.org/rfc/rfc9562.html",
            "Time-ordered UUIDs, standardised."),
        Ref("Google Spanner: TrueTime and external consistency",
            "https://cloud.google.com/spanner/docs/true-time-external-consistency",
            "What it takes to trust clocks across machines."),
        Ref("Maelstrom workloads (echo, unique-ids)",
            "https://github.com/jepsen-io/maelstrom/blob/main/doc/workloads.md",
            "The real test harness and its messages."),
    ),
    try_next=(
        "Do stage 1 in labs/unique_ids/main.py and watch the replies turn green.",
        "Try a counter per node first and watch the Dups tile: then fix it.",
        "Build a Snowflake id that ignores the clock jump, and wait for an orange node.",
    ),
)

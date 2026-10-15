"""Lab consistent_hashing, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Consistent hashing"
SUMMARY = "8 cache servers in front of a database. Route keys so a change moves few of them."
PARAMS = {"rate": "key reads per second"}

INCIDENT = IncidentText("Change", "the change", "the next change")
VERBS = {"lost": "LOST", "back": "BACK", "join": "JOIN", "leave": "LEAVE", "stop": "STOP", "start": "START"}
CAUSES = {
    "kernel_panic": "a kernel panic",
    "spot_reclaimed": "the cloud reclaimed its spot instance",
    "oom_killed": "the OOM killer stopped the cache",
    "disk_full": "its disk filled up",
    "evening_peak": "the evening peak",
    "sale_capacity": "extra capacity for a sale",
    "autoscaler_cpu": "the autoscaler saw high CPU",
    "rolling_deploy": "a rolling deploy",
    "config_restart": "a config change needs a restart",
    "kernel_patch": "a kernel security patch",
}

STAGES = [
    StageText("Modulo",
              "Challenge: one node more or less remaps almost every key; the DB floods. Use a ring.",
              "Stage 1: put the nodes on a hash ring in Router"),
    StageText("Hash ring",
              "Challenge: few keys move now, but some nodes own far more keys than others.",
              "Stage 2: give every node ~200 virtual nodes"),
    StageText("Ring + virtual nodes",
              "Solved: a change moves ~1/N of the keys, and every node owns a fair share.",
              "All stages done"),
]

GOALS = {
    "balance": GoalText("Keys/node ≤ 1.4x", "add virtual nodes"),
    "moved": GoalText("Moved ≤ 3/N", "use a hash ring"),
    "hits": GoalText("Hits kept ≥ 90%", "move fewer keys"),
    "db": GoalText("DB load ≤ 2x", "move fewer keys"),
}

LEGEND = {"fair": "fair load", "busy": "busy", "hot": "hot", "out": "out", "read": "read",
          "miss": "miss", "limit": "limit"}

STRINGS = {
    # incidents
    "title_crash": "Node lost",
    "title_scale": "Scale out",
    "title_deploy": "Restart",
    "lost": "{node} is down: {cause}",
    "lost_plain": "a node is down: {cause}",
    "replaced": "{node} is replaced, with an empty cache",
    "replaced_plain": "the node is replaced, with an empty cache",
    "join": "{node} joins: {cause}",
    "join_plain": "a node joins: {cause}",
    "leave": "{node} leaves again",
    "leave_plain": "the extra node leaves again",
    "stop": "{node} stops: {cause}",
    "stop_plain": "a node stops: {cause}",
    "start": "{node} is back, with an empty cache",
    "start_plain": "the node is back, with an empty cache",
    # goal values
    "per_n": "{value:.1f}/N",
    # the panel
    "tile_hits": "Hits",
    "tile_db": "DB/s",
    "tile_spread": "Spread",
    "bar_cache": "Cache",
    "bar_db": "Database",
    "limit": "DB {limit:.0f}/s",
    "chart_limit": "DB {limit:.0f}/s",
    "reads": "Reads",
    "head_change": "{node}: {moved:.0%} of keys moved, hits {hits:.0%}",
    "head_hot": "{node} holds {spread:.1f}x its share of keys",
    "head_ok": "{hits:.0%} hits; the database reads {db:.0f}/s",
    "note_chart": "Chart: database reads/s; refused in red.",
    "note_nodes": "Nodes: colour = share of keys vs average.",
    # the lanes picture (the clients' view): states under the cluster, at most 13 letters
    "lanes_hits": "HITS {share:.0%}",
    "lanes_misses": "MISSES {share:.0%}",
    # the fan-in picture: the router (the door), the cache servers, the database (the store)
    "fan_router": "router",
    "fan_down": "{node} down",
    "fan_db": "{state} DB {db}/s",
    # errors in your code
    "bad_node": "node_for returned '{node}', which is not in the cluster now ({live})",
}

LESSON = Lesson(
    title="Consistent hashing",
    one_liner="Spread keys over cache servers so that adding or losing one moves only its own share of the keys.",
    learn=(
        "hash(key) % N spreads keys evenly, but when N changes almost every key gets a new server: "
        "from 8 to 7 nodes about 7 keys in 8 move. Each moved key is a miss on a cold server, so the "
        "database suddenly gets most of the traffic the cache was absorbing.",
        "A hash ring puts every node on a circle at hash(node). A key belongs to the first node "
        "clockwise from hash(key). When a node leaves, only its keys move, to the next node; when one "
        "joins, it takes keys only from its neighbour. About 1/N of the keys move.",
        "With one point per node the arcs are uneven: some nodes own two or three times their share. "
        "Virtual nodes put each node on the ring many times (100 to 200 points), so every node owns "
        "about 1/N, and a node that leaves spreads its keys over all the others, not just one.",
        "Alternatives with the same goal: rendezvous (highest random weight) hashing, jump consistent "
        "hash (no memory, but nodes must be numbered 0..N-1), and Maglev's lookup table.",
    ),
    watch_for=(
        "Modulo: at each change most read dots turn red (misses) and the database bar jumps past its limit.",
        "Hash ring: a change barely shows, but some nodes stay orange or red: they own more keys.",
        "Ring + virtual nodes: every node stays blue, and a change only makes a few misses.",
        "The goals: keys moved and spread are your router's; hits and database load are what users feel.",
    ),
    build=(
        ("A ring with virtual nodes (Python)",
         "ring = sorted((stable_hash(f'{node}#{i}'), node) for node in nodes for i in range(200))\n"
         "points = [h for h, _ in ring]\n\n"
         "def node_for(key):\n"
         "    i = bisect.bisect_left(points, stable_hash(key)) % len(ring)\n"
         "    return ring[i][1]"),
        ("Jump consistent hash (Lamping & Veach)",
         "def jump(key: int, buckets: int) -> int:\n"
         "    b, j = -1, 0\n"
         "    while j < buckets:\n"
         "        b = j\n"
         "        key = (key * 2862933555777941757 + 1) % 2**64\n"
         "        j = int((b + 1) * (2**31 / ((key >> 33) + 1)))\n"
         "    return b"),
    ),
    checklist=(
        "Never route with hash(key) % N when N can change: count the keys that move on a change.",
        "Use a hash that is stable across processes and versions (md5, xxhash, murmur); not Python's hash().",
        "Give every node 100-200 virtual nodes, or weight them by capacity.",
        "Measure the spread: keys and requests on the busiest node vs the average.",
        "Expect a burst of misses on every change anyway, and keep the database able to take it.",
        "Hot keys are a separate problem: no hashing spreads one very popular key.",
    ),
    refs=(
        Ref("Karger et al.: Consistent hashing and random trees (1997)",
            "https://www.cs.princeton.edu/courses/archive/fall09/cos518/papers/chash.pdf",
            "The original paper, written for web caches; the start of Akamai."),
        Ref("Amazon Dynamo (2007)",
            "https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf",
            "A ring with virtual nodes in production, and why they weight nodes by capacity."),
        Ref("Lamping & Veach: A fast, minimal memory, consistent hash algorithm (2014)",
            "https://arxiv.org/abs/1406.2294",
            "Jump consistent hash: a few lines, no ring."),
        Ref("Ably: Implementing efficient consistent hashing",
            "https://ably.com/blog/implementing-efficient-consistent-hashing",
            "How Ably spreads channels over a changing cluster."),
        Ref("Discord: How Discord scaled Elixir to 5,000,000 concurrent users",
            "https://discord.com/blog/how-discord-scaled-elixir-to-5-000-000-concurrent-users",
            "A hash ring routes every guild to its server; they had to make it fast."),
        Ref("libketama: consistent hashing for memcached clients",
            "https://www.metabrew.com/article/libketama-consistent-hashing-algo-memcached-clients",
            "The ring every memcached client copied, from Last.fm."),
    ),
    try_next=(
        "Do stage 1 in labs/consistent_hashing/main.py and watch the next change barely show.",
        "Do stage 2 and watch the orange and red nodes turn blue.",
        "Try --set rate=900: a modulo change now pushes the database past its limit.",
    ),
)

"""Lab cache, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Cache stampede"
SUMMARY = "Every read waits for a slow database. Cache the hot keys, then survive a cache flush."
PARAMS = {"rate": "pages per second (each page reads 3 keys)", "ttl": "seconds a cached value lives"}

INCIDENT = IncidentText("Flush", "the flush", "the next flush")
VERBS = {"flush": "FLUSH", "end": ""}
CAUSES = {
    "deploy_restart": "a deploy restarted the cache nodes",
    "config_roll": "a config change rolled the cache cluster",
    "out_of_memory": "the cache ran out of memory and restarted",
    "kernel_update": "a kernel update rebooted the cache hosts",
    "empty_replica": "the cache failed over to an empty replica",
    "cold_node": "a network blip made the cache client reconnect to a cold node",
}

STAGES = [
    StageText("No cache",
              "Challenge: every read waits for the database. Keep the hot keys in memory.",
              "Stage 1: cache-aside with a TTL"),
    StageText("Cache-aside",
              "Challenge: after a flush every miss hits the database at once. Load each key once.",
              "Stage 2: single-flight loads and jittered TTLs"),
    StageText("Stampede-safe",
              "Solved: hot keys come from memory, and one load per key refills the cache after a flush.",
              "Both stages done"),
]

GOALS = {
    "hits": GoalText("Hit ratio ≥ 80%", "add cache-aside with a TTL"),
    "dups": GoalText("Dup loads < 5%", "single-flight loads in get()"),
    "p99": GoalText("p99 < 100ms", "load each key once"),
}

LEGEND = {"idle": "idle", "hit": "hit", "shared": "waits on a load", "first": "first load",
          "dup": "duplicate load", "rejected": "rejected", "limit": "limit", "flush": "after a flush"}

STRINGS = {
    # incidents
    "flushed": "is empty: {cause}",
    "warn_db": "database reads {ratio:.1f}x normal",
    # goal values
    "failed": "failed",
    # the panel
    "tile_hits": "Hits",
    "tile_dups": "Dups",
    "tile_p99": "p99",
    "toplist": "Reads",
    "bar_users": "Users",
    "bar_db": "Database",
    "limit": "limit {limit:.0f}/s",
    "head_hit_db": "Flush: {ratio:.0f}x reads hit the database",
    "head_refilling": "Flush: the cache is refilling",
    "head_no_cache": "No cache: every read goes to the database",
    "head_cache": "Cache: {share:.0%} of reads from memory",
    "note_dots": "Dots are a sample of reads, slowed down (cosmetic).",
    "note_chart": "The chart: database reads per second.",
    # errors in your code
    "stuck": "a read has been running for over {seconds:.0f} s: does get() wait for something that never finishes?",
}

LESSON = Lesson(
    title="Cache stampede",
    one_liner="A cache hides a slow database, until it is empty and every miss hits the database at once.",
    learn=(
        "Cache-aside: read the cache; on a miss read the database, store the value with a TTL, and "
        "return it. With skewed traffic (a few hot keys) most reads come from memory.",
        "A flush (a deploy, a restart, a failover) empties the cache. Every read is now a miss. A hot "
        "key is read many times while its first load is still running, and each of those misses "
        "starts its own load: a stampede, or thundering herd.",
        "The duplicate loads queue behind each other on the database, so every load takes longer, "
        "so even more reads miss while it runs. Expensive hot keys (a home page, a top-10 list) "
        "make it worse.",
        "Single-flight: the first miss for a key starts the load; the others wait for that same "
        "load. One database read per key, however many readers.",
        "Jittered TTLs: keys loaded together after a flush would also expire together. A random "
        "TTL (say ±20%) spreads the expiries out.",
    ),
    watch_for=(
        "No cache: 'Users' is above the database limit, the queue fills, reads wait or fail.",
        "Cache-aside: calm until a flush, then deep orange duplicate loads and a p99 near a second.",
        "Stampede-safe: after a flush the database briefly works harder, but every key loads once.",
        "Single-flight does not cut the misses for different keys; it removes the duplicates.",
    ),
    build=(
        ("Go: golang.org/x/sync/singleflight",
         "v, err, _ := group.Do(key, func() (any, error) {\n"
         "    return db.Load(ctx, key)\n"
         "})"),
        ("Python asyncio: one future per key in flight",
         "if (fut := self.loading.get(key)) is not None:\n"
         "    return await asyncio.shield(fut)\n"
         "fut = self.loading[key] = loop.create_future()\n"
         "try:\n"
         "    fut.set_result(value := await db.read(key))\n"
         "    return value\n"
         "finally:\n"
         "    del self.loading[key]"),
        ("Jittered TTL (Redis)",
         "ttl = int(BASE_TTL * random.uniform(0.8, 1.2))\n"
         "await redis.set(key, value, ex=ttl)"),
    ),
    checklist=(
        "Know your hit ratio and what the database does at 0% (after a flush or a cold start).",
        "Single-flight (or leases) per key on the read path, per process at least.",
        "Jitter TTLs, and refresh hot keys early (probabilistic early expiration) instead of letting them expire.",
        "Warm the cache before a deploy takes traffic, or roll out slowly.",
        "Protect the database anyway: a bounded queue, timeouts, and load shedding.",
    ),
    refs=(
        Ref("AWS: Caching best practices",
            "https://aws.amazon.com/caching/best-practices/",
            "Cache-aside (lazy loading), TTLs, and the thundering herd."),
        Ref("Scaling Memcache at Facebook (NSDI 2013)",
            "https://www.usenix.org/conference/nsdi13/technical-sessions/presentation/nishtala",
            "Leases: one client refills a key, the others wait or use a stale value."),
        Ref("Go: singleflight",
            "https://pkg.go.dev/golang.org/x/sync/singleflight",
            "Duplicate-call suppression in a few lines."),
        Ref("Optimal Probabilistic Cache Stampede Prevention (VLDB 2015)",
            "https://www.vldb.org/pvldb/vol8/p886-vattani.pdf",
            "XFetch: refresh a key early, with a probability that grows as it nears expiry."),
    ),
    try_next=(
        "Do stage 1 in labs/cache/main.py and watch the hit ratio climb; then wait for a flush.",
        "Do stage 2 and watch the deep orange disappear after the next flush.",
        "Try --set ttl=5 and --set ttl=120: what happens to the hit ratio and to each flush?",
    ),
)

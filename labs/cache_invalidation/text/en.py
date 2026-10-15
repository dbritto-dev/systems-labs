"""Lab cache_invalidation, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Cache invalidation"
SUMMARY = "Prices change while thousands read them from a cache. Never serve or keep an old one."
PARAMS = {"rate": "page views per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"campaign": "PRICES", "import": "IMPORT", "slow": "SLOW", "restart": "REBOOT", "calm": "CALM"}
CAUSES = {
    "flash_prices": "a flash-sale campaign reprices the popular products",
    "repricing_bot": "a repricing bot follows a competitor's prices",
    "currency": "an exchange-rate update reprices the bestsellers",
    "black_friday": "Black Friday prices go live on the popular products",
    "supplier_feed": "the supplier's catalogue feed is imported in bulk",
    "catalog_sync": "the nightly catalogue sync runs in the middle of the day",
    "erp_export": "the ERP pushes a full stock export",
    "cross_az": "the app servers fail over to another zone, far from the cache and the database",
    "packet_loss": "a bad switch drops packets; every round trip retransmits",
    "noisy_neighbour": "a noisy neighbour saturates the network of the hosts",
    "oom_kill": "the cache node is killed for using too much memory",
    "kernel_update": "the cache node reboots for a kernel patch",
    "cache_deploy": "a new cache version is rolled out",
}

STAGES = [
    StageText("Cache, then database",
              "Challenge: the cache shows prices the DB refused. Write the DB, then delete the key.",
              "Stage 1: write the database first, then delete the key"),
    StageText("Write, then delete",
              "Challenge: a slow reader puts an old price back after the delete. Fill with a lease.",
              "Stage 2: lease_get on a miss, lease_set to fill; TTL 30 s"),
    StageText("Leased fills",
              "Solved: no stale price is served or kept, and the cache still takes the reads.",
              "All stages done"),
]

GOALS = {
    "hits": GoalText("Hit ratio ≥ 85%", "cache what you read"),
    "phantom": GoalText("Unsaved served = 0", "write the DB, then delete"),
    "stale": GoalText("Stale reads = 0", "fill with a lease"),
    "entries": GoalText("Stale keys = 0", "refuse late fills: leases"),
    "db": GoalText("DB reads ≤ 500/s", "fill the cache on a miss"),
}

LEGEND = {"idle": "idle", "hit": "cache hit", "miss": "miss: DB read", "stale": "stale read",
          "served": "fresh", "write": "write, delete", "refused": "fill refused",
          "incident": "incident"}

STRINGS = {
    # incidents
    "campaign_start": "{rate:.0f} price writes/s to the popular products, two per product: {cause}",
    "campaign_end": "the campaign is over",
    "import_start": "{rate:.0f} writes/s across the whole catalogue: {cause}",
    "import_end": "the import has finished",
    "slow_start": "every round trip takes {times:.0f}x longer: {cause}",
    "slow_end": "the network is fast again",
    "restart_start": "the cache node answers nothing and comes back empty: {cause}",
    "restart_end": "the cache node is back, empty",
    "warn_stale": "{n} stale reads served",
    "warn_phantom": "{n} reads served a price that was never saved",
    # goal values
    "count": "{n}",
    "per_s": "{n:.0f}/s",
    # the panel
    "tile_stale": "Stale",
    "tile_hits": "Hits",
    "tile_keys": "Old keys",
    "bar_reads": "Reads",
    "bar_db": "DB reads",
    "bar_writes": "Writes",
    "limit": "DB reads/s",
    "head_stale": "{n} stale reads in 10 s",
    "head_keys": "{n} stale keys in the cache",
    "head_campaign": "Campaign: popular prices rewritten",
    "head_import": "Import: the catalogue rewritten",
    "head_slow": "Slow network: wider race windows",
    "head_restart": "Cache restart: reads go to the DB",
    "head_ok": "Every read is fresh",
    # the pictures
    "state_stale": "{n} STALE KEYS",
    "state_down": "CACHE DOWN",
    "state_slow": "SLOW NETWORK",
    "state_writes": "MANY WRITES",
    "pic_state": "3 app servers, cache, DB: {state}",
    # the relay picture: the words under the cache
    "relay_cache": "cache {hits:.0%} hits",
    "relay_stale": "stale keys: {n}",
    "relay_down": "cache down",
    "relay_writes": "MANY WRITES",
    "note": "Dots are a sample of reads and writes, slowed down (cosmetic).",
    "subtitle": "per second, last 1 s",
    "title": "Reads, writes",
    # errors in your code
    "stuck": "a request has been running for over {seconds:.0f} s: do read() and update() return?",
    "bad_read": "read() returned {value}, not a record from the cache or the database",
}

LESSON = Lesson(
    title="Cache invalidation",
    one_liner="A cache in front of a database is a second copy of the data; every write has to fix it, "
              "and every slow reader can break it again.",
    learn=(
        "Write the cache first and the database second, and two things go wrong. When the database "
        "refuses the write (a lock timeout, a constraint), the cache serves a price that was never "
        "saved. When two writers overlap, the cache can end with one's value and the database with "
        "the other's. Either stays until the TTL runs out.",
        "Cache-aside fixes the order: write the database, then delete the key (do not set it). A "
        "failed write leaves the cache alone; a delete cannot race another writer's value, and the "
        "next reader loads the truth.",
        "One race remains. A reader misses, reads the database (the old price), and stalls: a "
        "garbage-collection pause, a slow reply. Meanwhile a writer commits and deletes the key. "
        "Then the reader stores what it read: the old price, after the delete, for the whole TTL. "
        "Nobody will delete it again until the next write.",
        "Leases (Facebook's memcache, 2013) close it. A miss hands the reader a token; a delete of "
        "the key invalidates every token issued for it; the cache refuses a fill whose token is no "
        "longer valid. A late, stale fill is simply dropped, and the next reader loads the new "
        "price. A version number does the same job: the cache keeps the newest version it has seen "
        "(even after a delete) and refuses an older one.",
        "Keep a TTL anyway, short enough to bound the damage of anything you did not think of: a "
        "delete lost in a network blip, a bug in a writer. It is a safety net, not the way to be fresh.",
    ),
    watch_for=(
        "Cache, then database: during the price campaign, red reads at the door: prices the database "
        "refused, and stale ones.",
        "Write, then delete: no unsaved price, but red fills in the cluster picture put old prices back "
        "after a delete, and readers get them for minutes.",
        "Leased fills: late fills are refused (orange) instead; stale reads and stale keys stay at 0.",
    ),
    build=(
        ("Python: cache-aside writes",
         "async def update(key, record):\n"
         "    await db.write(key, record)      # if it raises, the cache is untouched\n"
         "    await cache.delete(key)          # the next reader loads the new record"),
        ("Python: leased fills",
         "lease = await cache.lease_get(key)\n"
         "if lease.value is not None:\n"
         "    return lease.value\n"
         "record = await db.read(key)\n"
         "await cache.lease_set(key, record, lease.token, ttl=30)  # refused after a delete\n"
         "return record"),
        ("Redis: a versioned fill (Lua, atomic)",
         "-- KEYS[1] = key, ARGV = value, version, ttl; the writer bumps 'ver:'..key on every write\n"
         "if tonumber(redis.call('GET', 'ver:'..KEYS[1]) or 0) > tonumber(ARGV[2]) then return 0 end\n"
         "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[3]) return 1"),
    ),
    checklist=(
        "Writers change the database first and invalidate the cache second; never the other way round.",
        "Invalidate with a delete, not a set: a set races other writers.",
        "Fills on a miss are conditional: a lease token or a version, so a late fill cannot undo a delete.",
        "Every cached entry has a TTL, short enough that a missed invalidation heals on its own.",
        "Count stale reads (sample a key from cache and database) and alert on them.",
        "Watch the hit ratio and the database's read rate after a cache restart.",
    ),
    refs=(
        Ref("Nishtala et al.: Scaling Memcache at Facebook (NSDI 2013)",
            "https://www.usenix.org/conference/nsdi13/technical-sessions/presentation/nishtala",
            "Leases against stale sets and thundering herds, section 3.2.1."),
        Ref("Microsoft: Cache-Aside pattern",
            "https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside",
            "Load on a miss, invalidate on a write, and why the cache can still be inconsistent."),
        Ref("AWS: Caching best practices",
            "https://aws.amazon.com/caching/best-practices/",
            "Lazy loading, write-through and TTLs."),
        Ref("Redis: Client-side caching",
            "https://redis.io/docs/latest/develop/reference/client-side-caching/",
            "Invalidation messages, and the race between a read and an invalidation."),
        Ref("Martin Fowler: Two hard things",
            "https://martinfowler.com/bliki/TwoHardThings.html",
            "\"There are only two hard things in Computer Science: cache invalidation and naming things.\""),
    ),
    try_next=(
        "Do stage 1 in labs/cache_invalidation/main.py and watch the unsaved prices disappear.",
        "Then switch to the cluster picture (v) during a campaign and look for red fills.",
        "Do stage 2 and watch the same late fills turn orange: refused.",
    ),
)

"""Lab conn_pool, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Connection pool"
SUMMARY = "Every request opens a database connection. Pool them, cap the pool, fail fast."
PARAMS = {"rate": "user requests per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"slow": "SLOW", "fast": "FAST", "spike": "SPIKE", "calm": "CALM"}
CAUSES = {
    "autovacuum": "autovacuum is rewriting the orders table",
    "report_locks": "a long report holds locks on the orders table",
    "backup_disks": "a backup saturates the disks",
    "dropped_index": "a deploy dropped an index, queries scan the table",
    "marketing_email": "a marketing email went out",
    "cron_fanout": "a cron job fans out to every user",
    "mobile_release": "a mobile release made every app refresh at once",
}

STAGES = [
    StageText("New connection",
              "Challenge: every request opens and closes its own connection. Reuse them in a pool.",
              "Stage 1: keep released connections and hand them out again"),
    StageText("Pool",
              "Challenge: when the database slows down, the pool grows past its 50 connections. Cap it.",
              "Stage 2: never open more than max_size; wait for a release"),
    StageText("Bounded pool",
              "Challenge: capped, but requests queue for a connection for seconds. Give up sooner.",
              "Stage 3: raise PoolTimeout after timeout seconds"),
    StageText("Bounded pool + timeout",
              "Solved: connections are reused, capped below the limit, and waits stay short.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "the pool must hand out conns"),
    "reuse": GoalText("Reuse ≥ 90%", "keep released connections"),
    "errors": GoalText("Conn errors = 0", "cap the pool at max_size"),
    "wait": GoalText("p99 wait < 1s", "raise PoolTimeout sooner"),
    "recovered": GoalText("Recovered ≥ 95%", "hand conns to waiters"),
}

LEGEND = {"idle": "idle", "query": "query", "waits": "waits for a conn", "opens": "opens a conn",
          "failed": "failed", "served": "served", "idle_conn": "idle conn", "limit": "limit",
          "incident": "incident"}

STRINGS = {
    "note_dots": "Dots are a sample, slowed down (cosmetic).",
    # the cluster picture: the topology under the grid
    "topology": "pool → database",
    # incidents
    "slowdown": "Slowdown",
    "spike": "Spike",
    "is_slow": "is slow: {cause}",
    "fast_again": "is fast again",
    "gets_traffic": "gets {times:.0f}x traffic: {cause}",
    "traffic_normal": "traffic is back to normal",
    "warn_refused": "too many connections: {n:.0f} refused",
    "warn_wait": "requests wait over 1 s for a conn",
    # the panel
    "tile_reuse": "Reuse",
    "tile_conns": "Conns",
    "tile_wait": "p99 wait",
    "toplist": "Requests",
    "bar_ask": "Users ask",
    "bar_served": "Served",
    "bar_failed": "Failed",
    "head_refused": "Too many connections: {n} refused",
    "head_fail_fast": "Failing fast: {n} gave up waiting",
    "head_waiting": "{n} requests wait for a connection",
    "head_slow_ok": "The database is slow; the pool holds up",
    "head_spike_ok": "Traffic spike; the pool holds up",
    "head_pool": "Pool: {n} connections open",
    "limit_max": "{n} max",
    "note_chart": "The chart: open connections (busy, idle).",
    # errors in your code
    "closed": "query on a closed connection",
    "too_many": "too many connections ({n} open)",
    "stuck": "a request has waited for a connection for over {seconds:.0f} s: "
             "does release() wake up the requests waiting in acquire()?",
}

LESSON = Lesson(
    title="Connection pool",
    one_liner="Opening a database connection is slow and the database allows only so many. Pool them, cap the pool, fail fast.",
    learn=(
        "A database connection is expensive to open: a TCP and TLS handshake, authentication, and on "
        "PostgreSQL a whole new backend process. A query on an open connection takes a few milliseconds. "
        "Opening one per request multiplies the work and the latency.",
        "A pool keeps released connections open and hands them to the next request. Most requests then "
        "pay nothing to connect.",
        "An unbounded pool grows with demand. When the database slows down, requests hold connections "
        "longer, the pool opens more, and it hits the database's max_connections: new requests are "
        "refused. More connections do not mean more throughput either: past the number of cores, "
        "everything just gets slower.",
        "A bounded pool caps connections below the limit and makes requests wait for a free one. That "
        "protects the database, but when it stays slow the queue of waiting requests grows without end.",
        "An acquire timeout bounds the wait: after it, the request fails fast and the caller can retry, "
        "degrade or show an error, instead of piling up behind the backlog.",
    ),
    watch_for=(
        "New connection: every dot is deep orange (opening a connection), and a slowdown hits the 50 limit.",
        "Pool: white dots reuse connections, but the slowdown still grows the pool to 50 and refuses requests.",
        "Bounded pool: no refusals, but the users wait in orange, longer and longer while it is slow.",
        "Bounded pool + timeout: waits stop at 0.5 s; some requests fail fast while the database is slow.",
    ),
    build=(
        ("Python: asyncpg's built-in pool",
         "pool = await asyncpg.create_pool(dsn, min_size=5, max_size=20)\n"
         "async with pool.acquire(timeout=0.5) as conn:   # raises TimeoutError when none is free\n"
         "    rows = await conn.fetch(\"SELECT ...\")"),
        ("Java: HikariCP",
         "config.setMaximumPoolSize(20);\n"
         "config.setConnectionTimeout(500);   // ms to wait for a connection before failing"),
        ("PostgreSQL: a pooler in front of many app servers (PgBouncer)",
         "[pgbouncer]\n"
         "pool_mode = transaction\n"
         "default_pool_size = 20\n"
         "max_client_conn = 1000"),
    ),
    checklist=(
        "Sum max_size over every app instance; keep it below the database's max_connections.",
        "Size pools from the database's cores, not from the request rate (small pools are often faster).",
        "Set an acquire timeout, shorter than the request's deadline.",
        "Metrics: open, in use and waiting connections; acquire wait time; refused connections.",
        "Many app servers? Put a pooler (PgBouncer, RDS Proxy) between them and the database.",
    ),
    refs=(
        Ref("HikariCP: About Pool Sizing",
            "https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing",
            "Why a small pool beats a big one: cores, disks, and contention."),
        Ref("PostgreSQL: Connections and Authentication",
            "https://www.postgresql.org/docs/current/runtime-config-connection.html",
            "max_connections, and what each connection costs the server."),
        Ref("Brandur: Managing Postgres connection limits",
            "https://brandur.org/postgres-connections",
            "Why Postgres connections are expensive, and pooling them with PgBouncer."),
        Ref("PgBouncer: features",
            "https://www.pgbouncer.org/features.html",
            "Session, transaction and statement pooling in front of PostgreSQL."),
        Ref("AWS: Amazon RDS Proxy",
            "https://aws.amazon.com/rds/proxy/",
            "A managed pooler that shares connections between many clients."),
    ),
    try_next=(
        "Do stage 1 in labs/conn_pool/main.py and watch the deep orange (new connections) disappear.",
        "Do stage 2 and watch the refusals stop, while the waits grow during a slowdown.",
        "Do stage 3 and watch the p99 wait stay under 1 s.",
        "Try max_size=50 in Pool: does a bigger pool make the slowdown any faster?",
    ),
)

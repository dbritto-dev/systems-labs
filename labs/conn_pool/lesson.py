from core.lessons import Lesson, Ref

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

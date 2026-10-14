"""Lab database_index, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Database index"
SUMMARY = "The table keeps growing and every query reads all of it. Add the indexes that fix it."
PARAMS = {"rate": "logins per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"import": "IMPORT", "report": "REPORT", "spike": "SPIKE", "calm": "CALM"}
CAUSES = {
    "partner_import": "a partner imports its user list",
    "backfill": "a migration backfills old accounts",
    "csv_upload": "an admin uploads a big CSV",
    "new_dashboard": "a new dashboard went live",
    "finance_export": "finance runs its month-end export",
    "ad_hoc_query": "an analyst runs ad hoc reports",
    "newsletter": "the newsletter went out",
    "login_storm": "a mobile app bug logs everyone out",
    "app_release": "a new app release",
}

STAGES = [
    StageText("Full scans",
              "Challenge: every query reads the whole table, and it keeps growing. Index the logins.",
              "Stage 1: a hash index email -> position for find_by_email"),
    StageText("Hash index",
              "Challenge: logins read one row, but every range report still scans everything.",
              "Stage 2: a composite (country, time) index with bisect"),
    StageText("Hash + composite index",
              "Solved: each query reads only the rows it returns, however big the table gets.",
              "All stages done"),
]

GOALS = {
    "lookups": GoalText("Rows/login ≤ 5", "index email -> position"),
    "ranges": GoalText("Rows/range ≤ 2x", "index (country, time)"),
    "p99": GoalText("p99 < 100ms", "read fewer rows per query"),
    "answered": GoalText("Answered ≥ 99%", "keep the indexes right"),
}

LEGEND = {"idle": "idle", "cheap": "few rows", "costly": "more rows read", "timed_out": "timed out",
          "served": "served", "limit": "limit", "incident": "incident"}

STRINGS = {
    # incidents
    "title_import": "Import",
    "title_report": "Report",
    "title_spike": "Spike",
    "start_import": "gets {rows:,.0f} imported rows: {cause}",
    "start_report": "runs {x:.0f}x more range queries: {cause}",
    "start_spike": "gets {x:.1f}x the logins: {cause}",
    "end": "is calm again",
    "warn_slow": "queries take {ms:.0f} ms",
    "warn_timeouts": "users give up waiting for the database",
    # goal values
    "ratio": "{value:.1f}x",
    "timeouts": "timeouts",
    # the panel
    "tile_lookup": "Login",
    "tile_range": "Range",
    "tile_p99": "p99",
    "bar_logins": "Logins",
    "bar_ranges": "Ranges",
    "bar_writes": "Writes",
    "queries": "Queries",
    "head_timeouts": "{n} users gave up waiting",
    "head_import": "Import: the table has {rows:,} rows",
    "head_report": "A report runs big range queries",
    "head_spike": "{x:.1f}x the logins",
    "head_calm": "{rows:,} rows; a login reads {read:,.0f}",
    "note_chart": "Chart: database busy time, % of 4 workers.",
    # the cluster picture: the topology under the grid
    "pic_state": "queue → 4 workers · {read:,.0f} rows/login: {state}",
}

LESSON = Lesson(
    title="Database index",
    one_liner="A query that reads every row gets slower as the table grows; an index reads only what it needs.",
    learn=(
        "Without an index, a database answers a query with a full scan: it reads every row and keeps "
        "the ones that match. That is fine for 1,000 rows and terrible for 10 million, and the table "
        "keeps growing: a query that was fast at launch slows down a little every day.",
        "A hash index maps a value to where its row lives (email -> position). An equality lookup "
        "reads one row. It cannot answer 'between': hashes have no order.",
        "A B-tree (here: a sorted list and bisect) keeps keys in order, so a range is one search for "
        "its start plus a walk to its end. A composite index (country, time) answers 'this country, "
        "in this time range' by reading only the rows it returns. Column order matters: equality "
        "columns first, then the range column.",
        "Indexes are not free: every insert updates every index, and they take memory. Index what "
        "your queries ask for, and check with EXPLAIN that they are used.",
    ),
    watch_for=(
        "Full scans: logins read the whole table; after an import the database falls behind and users time out.",
        "Hash index: logins read one row, but range reports still light up the chart orange.",
        "Hash + composite index: rows read per query stay tiny whatever the table size.",
        "The table keeps growing in every stage; only the cost of reading it changes.",
    ),
    build=(
        ("PostgreSQL: the two indexes of this lab",
         "CREATE UNIQUE INDEX users_email ON users (email);\n"
         "CREATE INDEX users_country_time ON users (country, signed_up_at);"),
        ("Check that a query uses its index",
         "EXPLAIN ANALYZE\n"
         "SELECT * FROM users\n"
         "WHERE country = 'BR' AND signed_up_at >= now() - interval '1 hour';\n"
         "-- look for 'Index Scan using users_country_time', not 'Seq Scan'"),
        ("Python: a sorted index with bisect",
         "lo = bisect_left(index, (start, -1))\n"
         "hi = bisect_left(index, (end, -1))\n"
         "rows = [heap.get(pos) for _, pos in index[lo:hi]]"),
    ),
    checklist=(
        "Every frequent query has an index; check with EXPLAIN on production-sized data.",
        "Equality columns first, the range column last, in composite indexes.",
        "Watch rows read per query (or 'rows examined'), not only latency: it warns you early.",
        "Do not over-index: each index costs writes and memory.",
        "Load-test with a table as big as next year's, not today's.",
    ),
    refs=(
        Ref("Use The Index, Luke",
            "https://use-the-index-luke.com/",
            "SQL indexing explained for developers: B-trees, composite indexes, ranges."),
        Ref("PostgreSQL: Indexes",
            "https://www.postgresql.org/docs/current/indexes.html",
            "Index types, multicolumn indexes and when they are used."),
        Ref("PostgreSQL: Using EXPLAIN",
            "https://www.postgresql.org/docs/current/using-explain.html",
            "Read a query plan: Seq Scan vs Index Scan, rows and cost."),
        Ref("SQLite: Query Planning",
            "https://www.sqlite.org/queryplanner.html",
            "How a planner uses an index to find rows, with pictures."),
    ),
    try_next=(
        "Do stage 1 in labs/database_index/main.py and watch the login tile drop to 1 row.",
        "Do stage 2 and watch the report incidents stop turning the chart orange.",
        "Try --set rate=60: which stage still keeps up?",
    ),
)

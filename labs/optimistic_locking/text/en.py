"""Lab optimistic_locking, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Optimistic locking"
SUMMARY = "Many requests read, change and write the same rows. Lose no update, and still serve them."
PARAMS = {"rate": "purchases per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"flash": "SALE", "import": "IMPORT", "slow": "SLOW", "calm": "CALM"}
CAUSES = {
    "flash_sale": "a flash sale opens on one product",
    "push_alert": "a push notification sends everyone to one product",
    "influencer": "an influencer links one product to millions",
    "price_error": "a pricing mistake makes one product nearly free",
    "supplier_feed": "the supplier's stock feed is imported in bulk",
    "recount": "a warehouse recount is loaded while the shop is open",
    "price_sync": "a nightly sync job rewrites the popular items",
    "cross_az": "the app servers fail over to another zone, far from the database",
    "packet_loss": "a bad switch drops packets; every round trip retransmits",
    "db_cpu": "a runaway report pins the database CPU",
    "noisy_neighbour": "a noisy neighbour saturates the database host",
}

STAGES = [
    StageText("Last write wins",
              "Challenge: two requests read a row, both write; one update is lost. Check the version.",
              "Stage 1: write with compare_and_set and raise Conflict"),
    StageText("Version check",
              "Challenge: nothing is lost, but busy rows answer 409. Re-read, merge and retry.",
              "Stage 2: retry on conflict with a jittered, capped backoff"),
    StageText("Retry and merge",
              "Solved: no update is lost, and users succeed even on the busiest row.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "adjust() must return"),
    "lost": GoalText("Lost updates = 0", "use compare_and_set"),
    "conflicts": GoalText("409s ≤ 1%", "retry: re-read and merge"),
    "fast": GoalText("p99 < 500ms", "cap the backoff"),
    "served": GoalText("Served ≥ 98%", "retry up to MAX_TRIES"),
}

LEGEND = {"idle": "idle", "first_try": "first try", "retries": "retry 1,2,3", "conflict": "conflict (409)",
          "lost": "lost update", "served": "served", "limit": "users/s", "incident": "incident"}

STRINGS = {
    # incidents
    "flash_start": "{times:.1f}x the traffic, most of it on one item: {cause}",
    "flash_end": "the sale is over",
    "import_start": "a job writes {rate:.0f} rows/s to the popular items: {cause}",
    "import_end": "the import has finished",
    "slow_start": "every query takes {ms:.0f} ms: {cause}",
    "slow_end": "the database is fast again",
    "warn_lost": "{n} updates lost",
    # goal values
    "count": "{n}",
    # the panel
    "tile_lost": "Lost",
    "tile_conflicts": "409s",
    "tile_retried": "Retried",
    "bar_users": "Users",
    "bar_writes": "Writes",
    "limit": "users/s",
    "head_lost": "{n} updates lost in 10 s",
    "head_conflicts": "{n} answered 409 in 10 s",
    "head_flash": "Flash sale: one row, most writes",
    "head_import": "A bulk import writes popular rows",
    "head_slow": "Slow queries: a wider race window",
    "head_ok": "Every update kept",
    # the pictures
    "state_lost": "LOST UPDATES",
    "state_conflicts": "CONFLICTS",
    "state_hot": "HOT ROW",
    "state_slow": "SLOW",
    "pic_state": "3 app servers → stock DB: {state}",
    "note": "Dots are a sample of writes, slowed down (cosmetic).",
    "subtitle": "per second, last 1 s",
    "title": "Writes",
    # errors in your code
    "stuck": "a request has been running for over {seconds:.0f} s: does adjust() ever return?",
}

LESSON = Lesson(
    title="Optimistic locking",
    one_liner="Read, change, write: when two requests do it to the same row at once, the second write "
              "erases the first.",
    learn=(
        "A read-modify-write (read the stock, subtract 2, write it back) takes two round trips. Another "
        "request can write the same row in between; then you write a value computed from old data, "
        "and its update is gone. This is the lost update: no error, just a wrong number.",
        "Optimistic locking gives every row a version. You write with the version you read: "
        "UPDATE ... SET value = $new, version = version + 1 WHERE id = $id AND version = $read. One "
        "statement checks and writes at once. If it matches no row, someone got there first: that is a "
        "conflict, and nothing was overwritten.",
        "A conflict is not a failure of the user's intent. Read the row again, apply the change to the "
        "fresh value (the merge), and try again. Wait a small random time first (jitter), so the "
        "requests that lost the same race do not collide again, and cap the waits and the tries.",
        "It is optimistic because it bets conflicts are rare: nobody holds a lock while they think. When "
        "one row is very hot (a flash sale), conflicts are common; retries still work, but SELECT ... "
        "FOR UPDATE, an atomic UPDATE stock = stock - 2, or a queue per item may serve it better.",
        "A lock in your process does not help: the other app servers do not see it. The check has to "
        "happen where the data is.",
    ),
    watch_for=(
        "Last write wins: every request is served, fast, and the flash sale loses hundreds of updates (red).",
        "Version check: no update is lost, but about one buyer in eight on the sale item gets a 409 (orange).",
        "Retry and merge: retries (orange dots) win on the next try or two; lost updates and 409s stay at 0.",
    ),
    build=(
        ("SQL: a version column and a conditional update",
         "UPDATE stock SET value = $1, version = version + 1\n"
         "WHERE id = $2 AND version = $3;\n"
         "-- 0 rows updated: someone wrote it since you read it -> re-read and retry"),
        ("Python: retry with full jitter",
         "for attempt in range(MAX_TRIES):\n"
         "    if attempt:\n"
         "        await asyncio.sleep(random.uniform(0, min(CAP, BASE * 2 ** attempt)))\n"
         "    row = await db.read(item)\n"
         "    if await db.compare_and_set(item, row.value + delta, row.version):\n"
         "        return\n"
         "raise Conflict(item)  # 409"),
        ("HTTP: ETags and If-Match",
         "GET /items/42          -> ETag: \"v17\"\n"
         "PUT /items/42  If-Match: \"v17\"\n"
         "-> 412 Precondition Failed when someone changed it first"),
    ),
    checklist=(
        "Every row that is read, changed and written back has a version (or a timestamp, or an ETag).",
        "Writes check the version in the same statement that writes: never check, then write.",
        "On a conflict, read again and re-apply the change; never retry the stale value.",
        "Retries wait a small random time that grows, with a cap on the wait and on the tries.",
        "Count conflicts: a high rate means a hot row, which may need a different design.",
        "Return 409 (or 412) when you give up, so the client knows nothing was changed.",
    ),
    refs=(
        Ref("Martin Fowler: Optimistic Offline Lock",
            "https://martinfowler.com/eaaCatalog/optimisticOfflineLock.html",
            "The pattern: detect a conflict with a version and roll the transaction back."),
        Ref("PostgreSQL: Transaction isolation",
            "https://www.postgresql.org/docs/current/transaction-iso.html",
            "Why two read-modify-writes in Read Committed can lose an update."),
        Ref("AWS: Optimistic locking with version number (DynamoDB)",
            "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBMapper.OptimisticLocking.html",
            "Conditional writes on a version attribute."),
        Ref("AWS Architecture Blog: Exponential backoff and jitter",
            "https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/",
            "Why full jitter makes contending clients finish sooner."),
        Ref("MDN: If-Match",
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/If-Match",
            "Optimistic locking over HTTP with ETags (412 Precondition Failed)."),
    ),
    try_next=(
        "Do stage 1 in labs/optimistic_locking/main.py and watch the red lost updates become orange 409s.",
        "Then watch the next flash sale: how many buyers of the sale item get an error?",
        "Do stage 2 and watch the 409s disappear while no update is lost.",
    ),
)

"""Lab zero_downtime_migration, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Zero-downtime migration"
SUMMARY = "Rename a column while old and new app instances share the database. Expand, backfill, contract."
PARAMS = {"rate": "user requests per second", "rows": "rows in the users table"}

INCIDENT = IncidentText("Migration", "the migration", "the next migration")
VERBS = {"open": "BEGIN", "close": "END", "deploy": "DEPLOY", "revert": "REVERT", "resume": "RESUME",
         "final": "FINAL", "add": "ADD", "rename": "RENAME", "drop": "DROP", "copied": "COPIED",
         "reads": "READS", "writes": "WRITES", "lag": "LAG", "busy": "BUSY", "out": "OUT", "back": "BACK",
         "done": "DONE", "stop": "STOP", "fail": "FAIL"}
CAUSES = {
    "weekly_release": "the weekly release",
    "feature_launch": "a feature launch",
    "hotfix": "a hotfix that also cleans up the schema",
    "canary_alarm": "a canary alarm on checkout latency",
    "error_spike": "an error spike in an unrelated service",
    "bad_config": "a config flag that looked wrong",
    "analytics_query": "a long analytics query on the replica",
    "replica_disk": "the replica's disk saturated by a snapshot",
    "network_blip": "a network blip between the zones",
    "traffic_peak": "a traffic peak from a marketing email",
    "nightly_job": "the nightly billing job",
    "cache_flush": "a cache flush that sends every read to the database",
}

STAGES = [
    StageText("Rename in place",
              "Challenge: the column is renamed at once, so every old instance fails until replaced.",
              "Stage 1: expand/contract (write both, drop last)"),
    StageText("Expand/contract",
              "Challenge: no errors, but one huge copy blocks writes and misses rollback writes.",
              "Stage 2: backfill() in batches, verify()"),
    StageText("Throttled, verified backfill",
              "Solved: the rename rolls out with no errors, fast writes and no stale names.",
              "All stages done"),
]

GOALS = {
    "errors": GoalText("Errors = 0", "keep old column until final"),
    "p99": GoalText("Write p99 <40ms", "small batches, wait if busy"),
    "wrong": GoalText("Wrong names = 0", "dual-write; verify()"),
    "done": GoalText("Done in ≤60s", "drop the old column"),
}

LEGEND = {"idle": "idle", "waiting": "waiting", "slow": "write > 40 ms", "served": "served", "failed": "failed",
          "wrong": "wrong name", "backfill": "copying", "trouble": "lag or busy"}

STRINGS = {
    "note_dots": "Dots are a sample, slowed down (cosmetic).",
    "note_chart": "The chart: the database's load, %: the app (white), other work (orange), your copies (purple).",
    # the window
    "open": "the next release renames users.{old} → {new}",
    "open_cause": "{cause} renames users.{old} → {new}",
    "closed": "the migration window closes",
    "not_done": "not done",
    # its steps (events)
    "step_deploy": "v{v} rolls out",
    "step_rollback": "rolled back halfway: {cause}",
    "step_forward": "v{v} rolls forward again",
    "step_released": "v{v} is final",
    "step_add": "{col} added (NULL)",
    "step_rename": "{col}",
    "step_drop": "{col} dropped",
    "step_copied": "every row in {new}",
    "step_read_new": "reads from {new}",
    "step_read_old": "reads from {old}",
    "step_write_new": "no more writes to {old}",
    "step_write_both": "writes to {old} again",
    "step_lag_start": "the replica falls behind: {cause}",
    "step_lag_end": "the replica caught up",
    "step_peak_start": "the database gets busy: {cause}",
    "step_peak_end": "the database is calm",
    "step_shunned": "replica {lag:.0f}s behind: out",
    "step_back_in": "replica back in the pool",
    "step_done": "migrated in {s:.0f} s",
    "step_unfinished": "{old} is still there",
    "step_failed": "{why}",
    "step_cut": "migrate cut short",
    "err_missing": "no column {col}",
    "err_exists": "{col} already exists",
    # the state under the pictures
    "state_old": "ONLY {old}",
    "state_both": "BOTH · {pct:.0f}% COPIED",
    "state_new": "ONLY {new}",
    "state_failing": "{n} FAILED/s",
    "cluster_state": "v{va}: {na} · v{vb}: {nb} · lag {lag:.1f}s",
    "cluster_copied": " · copied {pct:.0f}%",
    # the relay picture: the instances on each release, under the fleet
    "relay_fleet": "v{va}:{na} v{vb}:{nb}",
    "relay_copied": "{pct:.0f}% COPIED",
    # the panel
    "tile_errors": "Errors",
    "tile_p99": "p99",
    "tile_wrong": "Wrong",
    "bars": "Columns",
    "bars_sub": "reads and writes, last 1 s",
    "bar_old": "old",
    "bar_new": "new",
    "bar_failed": "failed",
    "stat_wrong": "wrong",
    "stat_write_p99": "write p99",
    "limit": "write p99 > 40ms",
    "head_errors": "Old instances fail: column gone",
    "head_slow": "Writes wait behind the backfill",
    "head_shunned": "Replica out: reads hit the primary",
    "head_wrong_reads": "Reads return stale names",
    "head_calm": "Every instance runs one release",
    "head_copying": "Backfill: {pct:.0f}% of the rows copied",
    "head_stale": "{n} rows changed after their copy",
    "head_done": "Migrated: {old} → {new}",
    "head_paused": "Database busy: the backfill waits",
    "head_mixed": "v{va} on {old}, v{vb} on {new} instances",
    "head_window": "Migrating users.{old} → {new}",
    # errors in your code
    "stuck": "a request has run for over {seconds:.0f} s: does read_name or write_name wait for something that never finishes?",
}

LESSON = Lesson(
    title="Zero-downtime migration",
    one_liner="Never change a column in one step: expand, migrate the data and the code, then contract.",
    learn=(
        "A rolling deploy replaces app instances one at a time, so for a while the old release and the new "
        "one serve traffic side by side, on the same database. If the migration renames users.fullname to "
        "display_name at once, every old instance still running fails on a column that no longer exists; "
        "a rollback brings failing instances back. Every schema change must work with both releases.",
        "Expand/contract (parallel change): add the new column (instant: NULLs, no default to write), make "
        "the new release write both columns in one statement and keep reading the old one, fill the new "
        "column for the rows written before (the backfill), switch reads to it, stop writing the old one, "
        "and drop it last, once no release that needs it can come back.",
        "The backfill is the dangerous part. One UPDATE of every row locks them all until it commits, so "
        "writes wait seconds, loads the database and floods the replica. Copy in small batches, pause "
        "between them, and stop while the database is busy or the replica lags: tools like gh-ost and "
        "pt-online-schema-change throttle exactly like this.",
        "A copy is only right for the rows nobody changes afterwards through the old column alone. Until "
        "the release is final, a rollback brings back old instances that write only the old column, so "
        "verify before you switch: compare the two columns batch by batch, re-copy what differs, and only "
        "then read the new one and drop the old one.",
    ),
    watch_for=(
        "Rename in place: the door shuts red and Errors climbs while old instances run, again on the rollback.",
        "Expand/contract: no errors, but the copy shades the chart purple, Write p99 hits seconds, Wrong stays.",
        "Throttled, verified backfill: the purple load stays under the dashed line; verify fixes the stale rows.",
    ),
    build=(
        ("Rails (strong_migrations): rename a column in steps",
         "add_column :users, :display_name, :string      # 1 expand\n"
         "# 2 deploy: write both, read fullname\n"
         "User.in_batches(of: 1000) { |b| b.update_all('display_name = fullname'); sleep(0.1) }\n"
         "# 3 deploy: read display_name; 4 deploy: stop writing fullname\n"
         "remove_column :users, :fullname                  # 5 contract"),
        ("PostgreSQL: one batch of the backfill, with a lock timeout",
         "SET lock_timeout = '2s';\n"
         "UPDATE users SET display_name = fullname\n"
         " WHERE id >= 4000 AND id < 4100\n"
         "   AND display_name IS DISTINCT FROM fullname;"),
        ("gh-ost (MySQL): copy rows in chunks, throttled on load and replica lag",
         "gh-ost --alter='ADD COLUMN display_name VARCHAR(255)' \\\n"
         "  --chunk-size=1000 --max-load=Threads_running=25 \\\n"
         "  --max-lag-millis=1500 --throttle-control-replicas=replica1 --execute"),
    ),
    checklist=(
        "Every migration works with the release before it and the one after it (they run together).",
        "Add columns nullable or with a constant default; never rename or drop in the same release.",
        "Write both columns in one statement until the old one is gone; read the old one until verified.",
        "Backfill in small batches with a pause, and stop while load or replica lag is high.",
        "Verify (compare old and new) after the release is final; drop the old column last.",
    ),
    refs=(
        Ref("Stripe: Online migrations at scale",
            "https://stripe.com/blog/online-migrations",
            "Dual writing, backfilling, switching reads and removing the old data, at Stripe's scale."),
        Ref("Martin Fowler: Parallel Change",
            "https://martinfowler.com/bliki/ParallelChange.html",
            "Expand, migrate, contract: change an interface in three phases."),
        Ref("gh-ost: Throttle",
            "https://github.com/github/gh-ost/blob/master/doc/throttle.md",
            "How a production migration tool pauses its copy on load and replica lag."),
        Ref("strong_migrations",
            "https://github.com/ankane/strong_migrations",
            "Which schema changes are unsafe in Postgres and MySQL, and the safe way to do each."),
        Ref("PlanetScale: Backward compatible database changes",
            "https://planetscale.com/blog/backward-compatible-databases-changes",
            "The six steps of a safe column rename, and why each one is there."),
    ),
    try_next=(
        "Do stage 1 in labs/zero_downtime_migration/main.py and watch Errors stay at 0 through the rollback.",
        "Do stage 2 and watch Write p99 and the purple load stay under the dashed line.",
        "Set BATCH = 2000 in your file: why does a lagging replica now take the whole pool down?",
        "Skip verify(): which migrations leave wrong names, and why only those?",
    ),
)

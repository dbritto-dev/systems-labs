"""Lab replication_lag, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Replication lag"
SUMMARY = "Reads go to replicas that lag behind. Make users see their own writes and never go back in time."
PARAMS = {"rate": "user operations per second (15% writes)"}

INCIDENT = IncidentText("Lag", "the lag", "the next lag")
VERBS = {"lag": "LAG", "caught": "SYNC", "down": "DOWN", "up": "UP", "spike": "SPIKE", "calm": "CALM"}
CAUSES = {
    "analytics_query": "a long analytics query holds the replica back",
    "autovacuum": "autovacuum is rewriting a big table on the replica",
    "brownout": "a network brownout slows the replication stream",
    "kernel_patch": "a kernel patch reboots the replica",
    "oom_kill": "the replica ran out of memory and restarted",
    "bulk_import": "a bulk import floods the primary with writes",
    "marketing_email": "a marketing email makes everyone update their profile",
}

STAGES = [
    StageText("Any replica",
              "Challenge: users miss their own changes, and pages jump back in time. Read your writes.",
              "Stage 1: read only replicas that have your last write"),
    StageText("Read your writes",
              "Challenge: users see their writes, but pages still jump back in time. Never go back.",
              "Stage 2: also never read older than what the session saw"),
    StageText("Monotonic reads",
              "Solved: users see their own writes, never go back in time, and replicas take the reads.",
              "All stages done"),
]

GOALS = {
    "ryw": GoalText("Own writes = 0", "remember each session's LSN"),
    "mono": GoalText("Back in time = 0", "remember versions seen"),
    "primary": GoalText("Primary ≤ 35%", "prefer a fresh replica"),
}

LEGEND = {"fresh": "up to date", "behind": "behind", "down": "down", "read": "read",
          "replication": "write / replication", "wrong": "wrong read", "limit": "primary limit"}

STRINGS = {
    # incidents
    "title_restart": "Restart",
    "title_spike": "Write spike",
    "behind": "{name} falls {lag:.0f} s behind: {cause}",
    "caught_up": "{name} caught up",
    "restarts": "{name} restarts: {cause}",
    "back": "{name} is back and catching up",
    "spike": "every replica falls behind: {cause}",
    "spike_over": "the replicas caught up",
    "warn_ryw": "a user missed their own write",
    "warn_mono": "a page went back in time",
    # the panel
    "tile_ryw": "Missed",
    "tile_mono": "Back",
    "tile_primary": "Primary",
    "bar_replicas": "Replicas",
    "bar_primary": "Primary",
    "bar_writes": "Writes",
    "reads": "Reads",
    "head_behind": "{name} is {lag:.1f} s behind",
    "head_down": "{name} is restarting",
    "head_spike": "Every replica ~{lag:.1f} s behind",
    "head_wrong": "{n} wrong reads in 5 s",
    "head_ok": "Replicas within {lag}",
    "note": "Read dots slowed down; writes at their real lag.",
    # the lanes picture (the clients' view): states under the cluster, at most 13 letters
    "lanes_stale": "STALE READS",
    "lanes_primary": "PRIMARY {share:.0%}",
    "lanes_lag": "LAG {lag:.1f}s",
    # errors in your code
    "bad_pick": "Router.pick returned {name!r}: use 'primary' or one of r1..r{last}",
    "stuck": "a read has been waiting for over {seconds:.0f} s",
}

LESSON = Lesson(
    title="Replication lag",
    one_liner="Read replicas are a little behind the primary, and sometimes a lot. Route reads so users never notice.",
    learn=(
        "Asynchronous replication: a write commits on the primary and reaches each replica a moment later "
        "(milliseconds normally, seconds when a replica is busy, restarting, or flooded). A read from a "
        "replica returns the data as of that replica's position in the log (its LSN).",
        "Read your writes: right after a user changes something, a replica may not have it yet, and the "
        "user thinks the change was lost. Remember the log position of each session's last write, and only "
        "read from a replica that has applied it (or from the primary).",
        "Monotonic reads: if two reads of the same page land on two replicas, the second may be older than "
        "the first, and the page goes back in time. Remember the newest version the session has seen and "
        "never read from a replica that is behind it.",
        "Both are session guarantees: they cost a little bookkeeping per session, keep most reads on the "
        "replicas, and need no coordination between replicas.",
    ),
    watch_for=(
        "Any replica: red dots at a lagging replica: users missing their own writes, pages going back.",
        "Read your writes: the 'Missed' tile stays green, but 'Back' turns red while a replica lags.",
        "Monotonic reads: the lagging replica gets no reads until it catches up; the primary takes few.",
        "Writes crawl towards a lagging replica: the dots are its backlog.",
    ),
    build=(
        ("PostgreSQL: the position a replica has replayed",
         "-- on the primary, after a write:  SELECT pg_current_wal_lsn();\n"
         "-- on a replica:                   SELECT pg_last_wal_replay_lsn();\n"
         "-- read from the replica only if its replay LSN >= the session's LSN"),
        ("Session token in a cookie (any language)",
         "after_write:  session['lsn'] = db.primary.current_lsn()\n"
         "on_read:      replica = pick(r for r in replicas if r.lsn >= session['lsn'])\n"
         "              session['lsn'] = max(session['lsn'], version_read)"),
    ),
    checklist=(
        "Know your replication lag: graph it per replica, alert on seconds, not just on 'replica up'.",
        "Read your writes for the user who wrote (session LSN, or read the primary for a few seconds).",
        "Monotonic reads within a session (sticky replica, or the newest version seen).",
        "Take a lagging replica out of the read pool automatically; put it back once caught up.",
        "Bound staleness for everything else, and say so in the API ('may be up to 2 s old').",
    ),
    refs=(
        Ref("Jepsen: Read Your Writes",
            "https://jepsen.io/consistency/models/read-your-writes",
            "The session guarantee, defined precisely."),
        Ref("Jepsen: Monotonic Reads",
            "https://jepsen.io/consistency/models/monotonic-reads",
            "Never see an older state after a newer one."),
        Ref("Werner Vogels: Eventually Consistent",
            "https://www.allthingsdistributed.com/2008/12/eventually_consistent.html",
            "Read-your-writes, monotonic reads and session consistency in practice."),
        Ref("PostgreSQL: Hot Standby",
            "https://www.postgresql.org/docs/current/hot-standby.html",
            "Reading from replicas, replay lag and its trade-offs."),
        Ref("Amazon Aurora: replication",
            "https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.Replication.html",
            "Replica lag in a managed database, and how to route reads."),
    ),
    try_next=(
        "Do stage 1 in labs/replication_lag/main.py and watch the 'Missed' tile go green.",
        "Then wait for a lag incident: what happens to the 'Back' tile?",
        "Do stage 2 and watch the lagging replica get no reads until it catches up.",
    ),
)

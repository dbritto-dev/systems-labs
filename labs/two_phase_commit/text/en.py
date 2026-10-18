"""Lab two_phase_commit, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Two-phase commit"
SUMMARY = "A transfer touches 3 shards. Commit it on all of them, or on none."
PARAMS = {"rate": "transfers per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"overload": "BUSY", "refuse": "NO", "shard_crash": "CRASH", "coord_crash": "CRASH", "partition": "CUT",
         "back": "BACK", "heal": "HEAL", "calm": "CALM"}
CAUSES = {
    "report_oom": "a long report locks rows on n2; transfers pile up in the coordinator's memory",
    "report_locks": "a long report holds row locks: prepares hit lock timeouts",
    "check_constraint": "a migration adds a CHECK constraint that some rows fail",
    "frozen_accounts": "compliance freezes a batch of accounts",
    "shard_oom": "the shard is OOM-killed right after voting yes",
    "kernel_panic": "a kernel panic right after it voted yes",
    "host_reboot": "its host reboots for a kernel patch, mid-transaction",
    "coord_oom": "the coordinator is OOM-killed while it sends a commit",
    "deploy": "a deploy kills the coordinator without draining it",
    "node_evicted": "the coordinator's node is evicted for maintenance",
    "switch_port": "a switch port fails between the coordinator and the shard",
    "firewall_rule": "a firewall change blocks the shard's port",
    "bgp_flap": "a BGP flap cuts the route to the shard's zone",
}

STAGES = [
    StageText("One shard at a time",
              "Challenge: a shard says no half way and the others keep their writes. Use 2PC.",
              "Stage 1: prepare everywhere, commit only if every shard votes yes"),
    StageText("Two-phase commit",
              "Challenge: crashes leave transfers in doubt, rows locked. Log and recover.",
              "Stage 2: log the commit before sending it; shards ask until they know"),
    StageText("2PC with recovery",
              "Solved: every transfer commits on all shards or none, even across crashes.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "transfers must commit"),
    "rolled": GoalText("No votes undone 100%", "prepare; commit or abort"),
    "partial": GoalText("Partial commits = 0", "commit only if all voted yes"),
    "money": GoalText("Money conserved", "log commit, resend until ack"),
    "doubt": GoalText("In doubt ≤ 3s after", "shards ask; resend on boot"),
    "completed": GoalText("Completed ≥90% after", "release locks: resolve doubt"),
}

LEGEND = {"prepare": "prepare", "yes": "vote yes", "commit": "commit", "abort": "no / abort",
          "ask": "ask outcome", "doubt": "in doubt", "down": "down", "partial": "partial", "limit": "transfers in",
          "incident": "incident"}

STRINGS = {
    "fan_coordinator": "coordinator",
    "fan_state_shard": "{shard} DOWN",
    # incidents
    "overload_start": "{shard} is busy: {share:.0%} of prepares time out on locks: {cause}",
    "overload_end": "{shard} answers in time again",
    "refuse_start": "{shard} votes no on {share:.0%} of transfers: {cause}",
    "refuse_end": "{shard} votes yes again",
    "shard_crash_start": "{shard} crashes: {cause}",
    "shard_crash_end": "{shard} is back, with its prepared transfers and their locks",
    "coord_crash_start": "the coordinator crashes: {cause}",
    "coord_crash_end": "the coordinator is back; recover() runs",
    "partition_start": "{shard} is cut off from the coordinator: {cause}",
    "partition_end": "{shard} can talk to the coordinator again",
    "warn_crash": "the coordinator runs out of memory while sending a commit",
    "warn_blocked": "prepared rows stayed locked in doubt for up to {seconds:.1f} s",
    "warn_partial": "{n} transfers committed on some shards only",
    "warn_stuck": "{n} transfers still in doubt: their rows stay locked",
    # goal values
    "none": "none",
    # the panel
    "tile_partial": "Partial",
    "tile_money": "Money",
    "tile_doubt": "In doubt",
    "bar_votes": "Votes",
    "bar_decided": "Decisions",
    "bar_ended": "Transfers",
    "limit": "transfers in",
    "head_partial": "{n} partial transfers in 10 s",
    "head_down": "Coordinator down: {n} in doubt",
    "head_doubt": "{n} in doubt: rows locked",
    "head_failing": "Shards vote no: aborted",
    "head_ok": "Every transfer atomic",
    # the pictures
    "state_partial": "PARTIAL",
    "state_down": "COORDINATOR DOWN",
    "state_doubt": "IN DOUBT",
    "state_shard_down": "SHARD DOWN",
    "state_no": "VOTES NO",
    "pic_state": "n0 → n1 · n2 · n3: {state}",
    "note": "Dots are a sample of messages, slowed down (cosmetic).",
    "subtitle": "per second, last 1 s",
    "title": "Protocol",
}

LESSON = Lesson(
    title="Two-phase commit",
    one_liner="One transaction, several shards: every shard commits it or none does, even when a "
              "shard says no, a node crashes or messages are lost.",
    learn=(
        "Writing to each shard in turn is not atomic: when a later shard says no (a lock timeout, "
        "a constraint) or crashes, the earlier ones keep their writes. A transfer that took the "
        "customer's money but never paid the merchant has destroyed money.",
        "Two-phase commit splits the transaction in two. Phase 1, prepare: each shard locks its rows, "
        "checks them and writes a prepare record to disk, then votes. A yes is a promise: it can "
        "commit whatever happens, even after a crash. Phase 2: only if every vote is yes does the "
        "coordinator send commit; otherwise abort.",
        "Between its yes and the decision a shard is in doubt: it cannot commit (others may have "
        "voted no) and cannot abort (the coordinator may have decided commit). It must hold its "
        "locks and wait. That is the price of 2PC: while the coordinator is down, prepared rows stay "
        "locked and block every transaction that needs them.",
        "So the decision must survive the coordinator: it writes 'commit' to its log before sending "
        "it (that write is the commit point), sends it until every shard acknowledges, and after a "
        "restart sends again what the log holds. A shard in doubt asks until it learns the outcome. "
        "With presumed abort, a transaction the log does not know was never committed: abort.",
    ),
    watch_for=(
        "One shard at a time: when n2 says no, n1 already has the write: a partial commit (red) and "
        "money created or destroyed.",
        "Two-phase commit: no votes abort cleanly, but the coordinator's crash leaves shards in doubt "
        "(orange) forever, holding locks, and later transfers time out on those rows.",
        "2PC with recovery: shards stay in doubt while the coordinator is down (the honest cost), "
        "and are resolved a moment after it is back.",
    ),
    build=(
        ("PostgreSQL: each shard prepares, the coordinator decides",
         "BEGIN; UPDATE accounts SET balance = balance - 30 WHERE id = 'c17';\n"
         "PREPARE TRANSACTION 't42';          -- the vote: durable, locks kept\n"
         "COMMIT PREPARED 't42';              -- or ROLLBACK PREPARED 't42'\n"
         "SELECT gid, prepared FROM pg_prepared_xacts;   -- in doubt after a restart"),
        ("MySQL / XA: the same two phases across resource managers",
         "XA START 't42'; UPDATE accounts ...; XA END 't42';\n"
         "XA PREPARE 't42';\n"
         "XA COMMIT 't42';                    -- XA RECOVER lists the ones in doubt"),
        ("The coordinator: the decision is durable before anyone hears it",
         "votes = await gather(*(prepare(s) for s in shards))\n"
         "if all(votes): await log.write(txn, 'commit')   # the commit point\n"
         "for s in shards: retry_until_ack(s, decision)\n"
         "# on restart: resend every commit in the log; unknown txn -> abort"),
    ),
    checklist=(
        "A shard votes yes only after its prepare record (and the locks) are on disk.",
        "Commit only if every shard voted yes; a missing vote is a no.",
        "Log the commit decision before sending it, and resend it until every shard acknowledges.",
        "A prepared shard never decides alone: it asks the coordinator until it learns the outcome.",
        "Presumed abort: a transaction with no commit record was not committed.",
        "Alert on transactions in doubt for long: they hold locks (pg_prepared_xacts, XA RECOVER).",
    ),
    refs=(
        Ref("Martin Kleppmann: Designing Data-Intensive Applications, ch. 9",
            "https://dataintensive.net/",
            "Atomic commit and two-phase commit, the coordinator's failure and in-doubt transactions."),
        Ref("PostgreSQL: PREPARE TRANSACTION",
            "https://www.postgresql.org/docs/current/sql-prepare-transaction.html",
            "The participant's side of 2PC, and why prepared transactions should not be left behind."),
        Ref("Martin Kleppmann: Transactions: myths, surprises and opportunities",
            "https://martin.kleppmann.com/2015/09/26/transactions-at-strange-loop.html",
            "A talk on what ACID really means, distributed transactions included."),
        Ref("Wikipedia: Two-phase commit protocol",
            "https://en.wikipedia.org/wiki/Two-phase_commit_protocol",
            "The protocol, its blocking problem, and presumed abort."),
        Ref("Princeton COS 418: Two-phase commit",
            "https://www.cs.princeton.edu/courses/archive/fall16/cos418/docs/L6-2pc.pdf",
            "Lecture slides: the protocol step by step, and what to do on timeouts and failures."),
    ),
    try_next=(
        "Do stage 1 in labs/two_phase_commit/main.py and watch the no votes abort on every shard.",
        "Then watch the coordinator's crash: which shards stay orange, and why can they not decide?",
        "Do stage 2 and watch the in-doubt shards resolve a moment after the coordinator is back.",
    ),
)

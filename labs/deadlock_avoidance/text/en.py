"""Lab deadlock_avoidance, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Deadlock avoidance"
SUMMARY = "Transfers lock two accounts each. Never let them wait for each other in a circle."
PARAMS = {"rate": "transfers per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"payout": "PAYOUT", "refunds": "REFUND", "slow": "SLOW", "batch": "BATCH", "calm": "CALM"}
CAUSES = {
    "month_end": "the month-end payout run pays every merchant at once",
    "weekly_payout": "the weekly payout run starts while sales are at their peak",
    "instant_payouts": "a new instant-payouts feature sends money out as soon as it comes in",
    "reserve_release": "the rolling reserves are released back to the merchants",
    "cancelled_sale": "a flash sale is cancelled: every order is refunded while buyers keep checking out",
    "double_charge": "a bug charged buyers twice; support refunds them while they keep buying",
    "event_cancelled": "a concert is cancelled: the ticket seller refunds its buyers",
    "chargebacks": "a card network sends a wave of chargebacks for one merchant",
    "audit_disk": "the audit log's disk stalls now and then",
    "audit_failover": "the audit database fails over to its replica",
    "audit_compaction": "the audit store compacts its files in the middle of the day",
    "audit_backup": "a backup snapshots the audit store's volume",
    "fee_sweep": "the nightly fee sweep runs late, during the day's traffic",
    "interest": "interest is posted to merchants' balances, many accounts per job",
    "reconciliation": "the bank reconciliation job corrects many balances at once",
    "fx_settlement": "currency settlement moves money between many accounts at once",
}

STAGES = [
    StageText("Request order",
              "Challenge: A→B and B→A wait for each other forever; the service freezes. Add timeouts.",
              "Stage 1: lock timeouts; release all, back off, retry"),
    StageText("Timeouts and retry",
              "Challenge: no freeze, but timeouts, retries and slow transfers. Lock in one order.",
              "Stage 2: lock in ascending id order; audit after releasing"),
    StageText("One lock order",
              "Solved: no deadlock can form, transfers are quick, and every cent is accounted for.",
              "All stages done"),
]

GOALS = {
    "deadlocks": GoalText("Deadlocks = 0", "lock in one global order"),
    "completed": GoalText("Completed ≥ 99%", "time out, release, retry"),
    "p99": GoalText("p99 ≤ 100ms", "keep the locks briefly"),
    "retries": GoalText("Retries ≤ 0.1", "lock in order: no timeouts"),
    "money": GoalText("Lost updates = $0", "hold both locks to move"),
}

LEGEND = {"idle": "idle", "first_try": "first try", "retries": "retried, waits longer", "done": "done",
          "deadlock": "deadlock, failed", "account": "account", "incident": "incident"}

STRINGS = {
    # incidents
    "payout_start": "{rate:.0f} payouts/s between the hot accounts, both ways, and out to sellers: {cause}",
    "payout_end": "the payout run has finished",
    "refunds_start": "{rate:.0f} refunds/s from one big merchant to buyers who keep paying it: {cause}",
    "refunds_end": "the refunds are done",
    "slow_start": "{rate:.1f}% of audit writes stall for 0.2-0.6 s: {cause}",
    "slow_end": "the audit log is quick again",
    "batch_start": "{rate:.0f} batch jobs/s, each locking 10-25 accounts: {cause}",
    "batch_end": "the batch job has finished",
    "warn_frozen": "{n} deadlocks nobody broke; the longest lasted {seconds:.1f} s",
    "warn_broken": "{n} deadlocks, each broken by a lock timeout",
    "warn_retries": "{n} retries after lock timeouts",
    # goal values
    "count": "{n}",
    "money": "${amount}",
    # the panel
    "tile_deadlocks": "Deadlock",
    "tile_p99": "p99",
    "tile_retries": "Retries",
    "bar_asked": "Asked",
    "bar_done": "Answered",
    "bar_retries": "Retries",
    "title": "Transfers",
    "head_deadlock": "Deadlock x{n}: waits in a circle",
    "head_frozen": "Frozen: no free workers",
    "head_retries": "{n} retries in the last second",
    "head_payout": "Payouts: hot accounts both ways",
    "head_refunds": "Refunds: the usual flow reversed",
    "head_slow": "Slow audit writes",
    "head_batch": "Batch jobs lock many accounts",
    "head_ok": "Every transfer gets its locks",
    # the pictures
    "state_deadlock": "DEADLOCK x{n}",
    "state_frozen": "FROZEN: NO WORKERS",
    "state_waiting": "{n} WAIT FOR LOCKS",
    "state_payout": "PAYOUT RUN",
    "state_refunds": "REFUNDS",
    "state_slow": "SLOW AUDIT",
    "state_batch": "BATCH JOB",
    "pic_state": "{n} waiting: {state}",
    "note": "Dots are a sample of transfers, slowed down (cosmetic).",
}

LESSON = Lesson(
    title="Deadlock avoidance",
    one_liner="Two transfers that lock the same two accounts in opposite orders can wait for each other "
              "forever; one global lock order makes that impossible.",
    learn=(
        "A transfer locks both accounts so nobody writes them in between. Lock them in request order "
        "(from, then to) and A→B and B→A can each get their first lock and wait for the other's: a "
        "deadlock. Four things make one possible (Coffman, 1971): locks are exclusive, you hold one while "
        "waiting for another, nobody takes a lock away, and the waits form a cycle.",
        "Without a deadlock detector the two transfers wait forever. Worse, every transfer that touches A "
        "or B waits behind them while holding its own first lock, and the pile spreads to the hot "
        "accounts until every worker of the service is stuck: it freezes.",
        "Lock timeouts break the hold-and-wait: give up a lock wait after a short time, release "
        "everything, back off with jitter and try again. Nothing freezes, but every timeout throws away "
        "work, and under contention a timeout also fires on a wait that was merely long. Retries add load, "
        "and without jitter two transfers that collided retry in step and collide again (a livelock).",
        "One global lock order breaks the cycle: lock accounts in ascending id order, always. A cycle "
        "would need somebody to wait for a smaller id while holding a bigger one, and nobody does. A batch "
        "job locks all its accounts in that order before it moves anything. Keep a long lock timeout as a "
        "safety net only.",
        "Ordering stops deadlocks, not waiting: a lock held longer makes everyone behind it wait longer. "
        "Keep the critical section short: check, read and slow work (the audit log, a call to another "
        "service) go outside the locks.",
        "Databases do it too: PostgreSQL and MySQL detect a deadlock and kill one transaction (the client "
        "gets an error and retries). Lock rows in a consistent order (by primary key) and they never have to.",
    ),
    watch_for=(
        "Request order: during the payout run a red cycle in the cluster picture, then the door shuts and "
        "the server's gauge fills: every worker is stuck.",
        "Timeouts and retry: cycles appear and are broken in a fraction of a second, but orange retries "
        "fill the lanes, and p99 and retries cross their limits.",
        "One lock order: no cycle ever forms; the arrows between accounts stay short and white.",
    ),
    build=(
        ("Python: one lock order",
         "for account in sorted({src, dst}):\n"
         "    await locks.acquire(account, timeout=2.0)   # a safety net only\n"
         "try:\n"
         "    await ledger.move(src, dst, amount)\n"
         "finally:\n"
         "    locks.release_all()\n"
         "await audit.record(entries)                     # slow work, after the locks"),
        ("SQL: lock both rows in id order",
         "BEGIN;\n"
         "SELECT id FROM accounts WHERE id IN ($1, $2) ORDER BY id FOR UPDATE;\n"
         "UPDATE accounts SET balance = balance - $3 WHERE id = $1;\n"
         "UPDATE accounts SET balance = balance + $3 WHERE id = $2;\n"
         "COMMIT;"),
        ("PostgreSQL: a lock-wait safety net",
         "SET lock_timeout = '2s';        -- give up a lock wait (SQLSTATE 55P03)\n"
         "SET deadlock_timeout = '1s';    -- how long before the detector looks"),
    ),
    checklist=(
        "Every code path that takes more than one lock takes them in the same global order (by id).",
        "A batch takes all its locks up front, in that order, before it changes anything.",
        "Nothing slow runs while a lock is held: no network calls, no audit writes, no user input.",
        "Lock waits have a timeout, as a safety net; on timeout, release everything before you retry.",
        "Retries back off with jitter, a few times at most.",
        "Count deadlocks, lock-wait time and lock timeouts, and alert on them.",
    ),
    refs=(
        Ref("Wikipedia: Deadlock",
            "https://en.wikipedia.org/wiki/Deadlock_(computer_science)",
            "The four Coffman conditions, and prevention, avoidance and detection."),
        Ref("PostgreSQL: Explicit locking, deadlocks",
            "https://www.postgresql.org/docs/current/explicit-locking.html",
            "Deadlocks: \"acquire locks on multiple objects in a consistent order\"."),
        Ref("MySQL: How to minimize and handle deadlocks",
            "https://dev.mysql.com/doc/refman/8.0/en/innodb-deadlocks-handling.html",
            "Short transactions, a consistent order, and retrying the victim."),
        Ref("MySQL: Deadlock detection",
            "https://dev.mysql.com/doc/refman/8.0/en/innodb-deadlock-detection.html",
            "innodb_deadlock_detect, and why busy servers turn it off and rely on lock_wait_timeout."),
        Ref("Linux kernel: lockdep",
            "https://www.kernel.org/doc/html/latest/locking/lockdep-design.html",
            "A validator that checks every lock is always taken in the same order."),
        Ref("AWS Builders' Library: Timeouts, retries and backoff with jitter",
            "https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/",
            "Why retries need backoff and jitter."),
    ),
    try_next=(
        "Do stage 1 in labs/deadlock_avoidance/main.py and watch the freeze turn into retries.",
        "Switch to the cluster picture (v) during the payout run: cycles appear and break.",
        "Do stage 2 and watch the cycles disappear for good.",
    ),
)

"""Lab saga, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Sagas"
SUMMARY = "An order spans payments, stock and shipping. Never leave one half done."
PARAMS = {"rate": "orders per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"timeouts": "SLOW", "oom": "SLOW", "stockout": "EMPTY", "shipping": "DOWN", "crash": "CRASH",
         "back": "BACK", "calm": "CALM"}
CAUSES = {
    "psp_overload": "the payment provider is overloaded; answers come late",
    "psp_network": "packet loss between us and the payment provider",
    "inventory_gc": "long GC pauses in the inventory service",
    "inventory_lock": "a migration locks the inventory table",
    "carrier_slow": "the carrier's booking API is slow",
    "carrier_lb": "the carrier's load balancer drops answers",
    "carrier_slow_oom": "the carrier's API is slow; waiting sagas fill the orchestrator's memory",
    "flash_sale": "a flash sale sells out the popular items",
    "inventory_sync": "a bad inventory sync shows stock that is not there",
    "warehouse_count": "a warehouse recount finds items missing",
    "carrier_outage": "the carrier has an outage",
    "carrier_cert": "the carrier's TLS certificate expired",
    "carrier_ratelimit": "the carrier rate-limits our account",
    "deploy": "a deploy restarts the orchestrator",
    "oom_kill": "the orchestrator is OOM-killed",
    "node_evicted": "the orchestrator's node is drained for maintenance",
}

STAGES = [
    StageText("No rollback",
              "Challenge: a failed step leaves the card charged and the items held. Compensate.",
              "Stage 1: on StepFailed, undo the done steps, last first"),
    StageText("Compensations",
              "Challenge: timeouts and crashes still leave orders half done. Make sagas resumable.",
              "Stage 2: keys on every call, retries, a log, recover()"),
    StageText("Resumable sagas",
              "Solved: every order ends done or fully rolled back, even across crashes.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "place() must finish orders"),
    "rolled": GoalText("Rolled back 100%", "undo done steps, last first"),
    "consistent": GoalText("Half done = 0", "keys, retries, log, recover"),
    "once": GoalText("Double charges = 0", "charge with key=saga_id"),
    "completed": GoalText("Completed ≥ 95%", "retry timeouts with the key"),
    "fast": GoalText("p99 finish < 1s after", "recover without blocking"),
}

LEGEND = {"idle": "idle", "step": "step", "retry": "after a timeout", "undo": "compensation",
          "done": "completed", "orphan": "half done", "limit": "orders in", "incident": "incident"}

STRINGS = {
    # incidents
    "timeouts_start": "{share:.0%} of calls time out: {cause}",
    "timeouts_end": "answers come back in time again",
    "oom_start": "{share:.0%} of bookings time out: {cause}",
    "oom_end": "the carrier answers in time again",
    "stockout_start": "{share:.0%} of orders are out of stock: {cause}",
    "stockout_end": "the items are in stock again",
    "shipping_start": "the carrier refuses {share:.0%} of bookings: {cause}",
    "shipping_end": "the carrier takes bookings again",
    "crash_start": "the orchestrator dies mid-saga: {cause}",
    "crash_end": "a new orchestrator is up; recover() runs",
    "warn_crash": "the orchestrator runs out of memory and dies mid-saga",
    "warn_orphans": "{n} orders left half done",
    "warn_doubles": "{n} orders charged twice",
    # goal values
    "none": "none",
    # the panel
    "tile_orphans": "Half done",
    "tile_doubles": "Doubles",
    "tile_done": "Done",
    "bar_steps": "Steps",
    "bar_undos": "Undos",
    "bar_sagas": "Sagas end",
    "limit": "orders in",
    "head_orphans": "{n} orders left half done in 10 s",
    "head_down": "Orchestrator down: orders wait",
    "head_failing": "Steps fail: sagas roll back",
    "head_ok": "Every order done or rolled back",
    # the pictures
    "state_down": "RESTARTING",
    "state_orphans": "HALF DONE",
    "state_timeouts": "TIMEOUTS",
    "state_failing": "STEPS FAIL",
    "pic_state": "orders → payments · stock · shipping: {state}",
    "note": "Dots are a sample of calls, slowed down (cosmetic).",
    "subtitle": "per second, last 1 s",
    "title": "Sagas",
    # errors in your code
    "stuck": "a saga has been running for over {seconds:.0f} s: does place() ever return?",
}

LESSON = Lesson(
    title="Sagas",
    one_liner="One order, three services, no shared transaction: every step that happened must be "
              "undone when a later one fails, even across timeouts and crashes.",
    learn=(
        "A saga is a sequence of local transactions, one per service, each with a compensating "
        "action that semantically undoes it: refund the charge, release the stock, cancel the "
        "booking. There is no rollback across services, so the orchestrator runs the compensations "
        "itself, in reverse order, when a later step fails.",
        "A timeout is not a failure: the step may have happened and only the answer was lost. If you "
        "undo only the steps whose answers you got, the timed-out one stays done. Undo it anyway by "
        "an idempotency key (undoing what never happened does nothing), or retry it with the same key "
        "to learn what happened.",
        "The orchestrator itself can die mid-saga (a deploy, an OOM kill). Whatever it kept in memory "
        "is gone, so it writes each saga's state to durable storage before every phase (write-ahead), "
        "and a new instance resumes every unfinished saga from there: forward if it was running, "
        "backward if it was compensating.",
        "Resuming re-runs steps that may already have happened, so every step and every compensation "
        "must be idempotent, keyed by the saga id. That is what makes retries and recovery safe: the "
        "same key never charges twice.",
    ),
    watch_for=(
        "No rollback: when the carrier fails, charged customers get no order and items stay held (red).",
        "Compensations: failed steps are undone (orange), but a step that timed out and still "
        "happened, or a saga the crash cut short, is left half done.",
        "Resumable sagas: after the crash a new orchestrator finishes every saga; half done stays at 0.",
    ),
    build=(
        ("An orchestrator step: write ahead, then call with the saga id as the key",
         "await log.save(saga_id, {\"order\": order, \"status\": \"running\"})\n"
         "charge = await payments.charge(order, idempotency_key=f\"{saga_id}:charge\")\n"
         "# on failure: save status=compensating, then refund/release/cancel by the same keys"),
        ("PostgreSQL: the saga log, and the unfinished sagas to resume after a restart",
         "CREATE TABLE saga (id text PRIMARY KEY, status text NOT NULL, state jsonb NOT NULL,\n"
         "                   updated_at timestamptz NOT NULL DEFAULT now());\n"
         "SELECT id, state FROM saga WHERE status IN ('running', 'compensating');"),
        ("Temporal: a workflow engine persists the saga for you; compensations in reverse order",
         "try:\n"
         "    await workflow.execute_activity(charge, order, ...)\n"
         "    compensations.append(refund)\n"
         "    ...\n"
         "except ActivityError:\n"
         "    for undo in reversed(compensations):\n"
         "        await workflow.execute_activity(undo, order, ...)"),
    ),
    checklist=(
        "Every step has a compensation, and compensations run in reverse order.",
        "Compensations cannot fail for good: retry them until they succeed (alert if they keep failing).",
        "Every step and compensation takes an idempotency key derived from the saga id.",
        "A timeout means 'unknown': retry with the same key, or compensate by key; never ignore it.",
        "Persist the saga's state before each phase; resume unfinished sagas on startup.",
        "Mark the saga 'compensating' before the first undo, so a restart never goes forward again.",
    ),
    refs=(
        Ref("Garcia-Molina and Salem: Sagas (1987)",
            "https://www.cs.cornell.edu/andru/cs711/2002fa/reading/sagas.pdf",
            "The original paper: long-lived transactions as steps with compensations."),
        Ref("microservices.io: Pattern: Saga",
            "https://microservices.io/patterns/data/saga.html",
            "Orchestration and choreography, with an order example."),
        Ref("Azure Architecture Center: Saga distributed transactions pattern",
            "https://learn.microsoft.com/en-us/azure/architecture/patterns/saga",
            "Compensable, pivot and retryable steps, and the data anomalies to plan for."),
        Ref("AWS Prescriptive Guidance: Saga orchestration pattern",
            "https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/saga-orchestration.html",
            "An orchestrator with Step Functions, and idempotent compensations."),
        Ref("Temporal: Saga pattern made easy",
            "https://temporal.io/blog/saga-pattern-made-easy",
            "A workflow engine that persists and resumes sagas for you."),
    ),
    try_next=(
        "Do stage 1 in labs/saga/main.py and watch the orange compensations when the carrier fails.",
        "Then watch the next crash: which orders are left half done now, and why?",
        "Do stage 2 and watch a new orchestrator finish every saga the crash cut short.",
    ),
)

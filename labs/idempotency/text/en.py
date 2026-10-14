"""Lab idempotency, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Idempotency keys"
SUMMARY = "Payments get retried. Charge every payment once, whatever arrives twice."
PARAMS = {"rate": "payments per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"slow": "SLOW", "resets": "RESETS", "storm": "DOUBLE", "calm": "CALM"}
CAUSES = {
    "ledger_lock": "a migration is locking the ledger table",
    "disk_io": "a noisy neighbour is saturating the database disk",
    "vacuum": "autovacuum is rewriting the charges table",
    "failover": "the ledger database is failing over",
    "lb_reset": "the load balancer resets connections mid-answer",
    "deploy_drain": "a deploy drains connections before answers go out",
    "proxy_timeout": "a proxy times out and drops the answers",
    "sdk_bug": "a new mobile SDK sends every payment twice",
    "double_click": "users double-click Pay on a slow page",
    "proxy_retry": "a proxy retries requests on its own",
}

STAGES = [
    StageText("No idempotency",
              "Challenge: a retried payment is charged again. Remember each key and replay its answer.",
              "Stage 1: store each key's receipt and return it again"),
    StageText("Replays answers",
              "Challenge: a retry that arrives while the first try runs charges twice. Reserve the key.",
              "Stage 2: claim the key with store.add before charging"),
    StageText("Reserved keys",
              "Solved: every payment is charged once, and every try gets the same receipt.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "return receipts from charge"),
    "replay": GoalText("Replayed ≥ 95%", "return the stored receipt"),
    "once": GoalText("Double charges = 0", "claim the key with store.add"),
    "same": GoalText("Same receipt", "duplicates wait for first"),
    "fast": GoalText("p99 < 500ms after", "answer duplicates quickly"),
}

LEGEND = {"idle": "idle", "first_try": "first try", "retries": "retry 1,2,3", "double": "charged twice",
          "answered": "answered", "lost": "no answer", "limit": "1 per payment", "incident": "incident"}

STRINGS = {
    # incidents
    "slow_start": "is slow, {seconds:.1f} s per charge: {cause}",
    "slow_end": "is fast again",
    "resets_start": "loses {share:.0%} of answers: {cause}",
    "resets_end": "answers get through again",
    "storm_start": "gets {share:.0%} of payments twice: {cause}",
    "storm_end": "clients send each payment once again",
    "warn_double": "{n} payments charged twice",
    # goal values
    "none": "none",
    "doubles": "{n}",
    # the panel
    "tile_doubles": "Doubles",
    "tile_replayed": "Replay",
    "tile_retried": "Retried",
    "bar_tries": "Tries",
    "bar_charges": "Charges",
    "limit": "1/payment",
    "head_doubles": "{n} payments charged twice in 10 s",
    "head_slow": "The ledger is slow: tries pile up",
    "head_ok": "Every payment charged once",
    "state_slow": "SLOW",
    "state_double": "CHARGED TWICE",
    # the cluster picture: the topology under the grid
    "pic_state": "service → keys · ledger: {state}",
    "note": "Dots are a sample of tries, slowed down (cosmetic).",
    "subtitle": "per second, last 1 s",
    "title": "Payments",
    # errors in your code
    "stuck": "a payment has been running for over {seconds:.0f} s: does charge() ever return?",
}

LESSON = Lesson(
    title="Idempotency keys",
    one_liner="A lost answer or a slow charge makes clients retry. Without a key, every retry is another charge.",
    learn=(
        "Networks lose answers after the work is done: the card was charged, but the client never heard. "
        "The client cannot tell that apart from a charge that never happened, so it retries. Each retry "
        "of a non-idempotent call does the work again.",
        "An idempotency key is a unique id the client sends with the request and reuses on every retry. "
        "The server stores the result under the key and, when the key comes back, returns the stored "
        "result instead of doing the work again.",
        "Check-then-act is a race: if a retry arrives while the first try is still running, both see "
        "'no result yet' and both charge. Claim the key first, in one atomic step (INSERT ... ON "
        "CONFLICT DO NOTHING, Redis SET NX), and make duplicates wait for the result or answer 409.",
        "Keys expire. Keep them long enough to cover every retry (Stripe keeps them 24 hours), and no "
        "longer, so the store does not grow forever.",
    ),
    watch_for=(
        "No idempotency: when the ledger slows down, every retry is a second charge (red).",
        "Replays answers: late retries get the stored receipt, but retries that arrive while the "
        "first try is still charging still charge twice.",
        "Reserved keys: duplicates wait for the first try's receipt; double charges stay at 0.",
    ),
    build=(
        ("PostgreSQL: claim the key and charge in one transaction",
         "INSERT INTO idempotency_keys (key, status) VALUES ($1, 'in_progress')\n"
         "ON CONFLICT (key) DO NOTHING RETURNING key;\n"
         "-- no row returned: someone else has it -> wait for its response or answer 409"),
        ("Redis: claim with SET NX and an expiry",
         "ok = await redis.set(f\"idem:{key}\", \"in-progress\", nx=True, ex=86400)\n"
         "if not ok:\n"
         "    return await wait_for_stored_response(key)  # or 409 Conflict"),
        ("HTTP: the client sends the same key on every retry",
         "POST /v1/charges\n"
         "Idempotency-Key: 5f0c1c2e-6f3a-4c7e-9b1a-2d4e8f9a0b1c"),
    ),
    checklist=(
        "Every unsafe request (POST that moves money, sends mail, creates things) takes a key.",
        "The client creates the key once per operation and reuses it on every retry.",
        "Claim the key atomically before doing the work; never check-then-act.",
        "Store the full response (status and body) and return exactly that on a repeat.",
        "A repeat with a different body under the same key is an error (422), not a new charge.",
        "Keys expire after the longest retry window; clean them up.",
    ),
    refs=(
        Ref("Stripe: Idempotent requests",
            "https://docs.stripe.com/api/idempotent_requests",
            "How a real payments API takes, stores and expires keys."),
        Ref("Stripe engineering: Designing robust and predictable APIs with idempotency",
            "https://stripe.com/blog/idempotency",
            "Why lost answers make retries dangerous, and how keys fix it."),
        Ref("IETF draft: The Idempotency-Key HTTP header field",
            "https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/",
            "The header, and what servers should answer for a concurrent duplicate (409)."),
        Ref("AWS Builders' Library: Making retries safe with idempotent APIs",
            "https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/",
            "Client request tokens, and what to return for a repeat."),
    ),
    try_next=(
        "Do stage 1 in labs/idempotency/main.py and watch the Replay tile turn green.",
        "Then watch the next slow ledger: where do the double charges come from now?",
        "Do stage 2 and watch the doubles disappear, even when clients send everything twice.",
    ),
)

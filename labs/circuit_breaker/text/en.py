"""Lab circuit_breaker, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Circuit breaker"
SUMMARY = "One slow dependency takes every worker. Add timeouts, a bulkhead and a circuit breaker."
PARAMS = {"rate": "user requests per second", "workers": "workers in our service"}

INCIDENT = IncidentText("Slowdown", "the slowdown", "the next slowdown")
VERBS = {"slow": "SLOW", "fast": "FAST"}
CAUSES = {
    "ledger_lock": "a lock on the ledger table",
    "provider_brownout": "a network brownout to the payment provider",
    "payments_gc": "a GC storm in the payments service",
    "rate_limited": "the payment provider is rate-limiting us",
    "recs_gc": "a GC storm in the recommendations service",
    "cold_cache": "a cold model cache after a deploy",
    "slow_features": "a slow feature store",
    "noisy_neighbour": "a noisy neighbour on its database",
}

STAGES = [
    StageText("No protection",
              "Challenge: one slow dependency holds every worker, so all requests fail. Add timeouts.",
              "Stage 1: give up on a call after TIMEOUT"),
    StageText("Timeouts",
              "Challenge: slow calls still hold the workers for a second each. Fence each dependency.",
              "Stage 2: a Bulkhead per dependency"),
    StageText("Timeouts + bulkhead",
              "Challenge: the healthy path is safe, but users still wait 1 s on the slow one. Fail fast.",
              "Stage 3: a CircuitBreaker per dependency"),
    StageText("Timeouts + bulkhead + breaker",
              "Solved: the slow dependency is fenced off and fails fast, and the rest keeps working.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "Client must return results"),
    "calls": GoalText("Calls ≤ 1.2s", "time out after TIMEOUT"),
    "healthy": GoalText("Healthy ≥ 99%", "a Bulkhead per dependency"),
    "fast": GoalText("Fail fast <50ms", "a CircuitBreaker per dep"),
    "back": GoalText("Back ≥ 95%", "close the breaker again"),
}

LEGEND = {"idle": "idle", "fast_call": "fast call", "waits_worker": "waits for a worker", "slow_call": "slow call",
          "refused": "refused", "failed": "failed", "served": "served", "workers": "workers",
          "incident": "incident"}

STRINGS = {
    "note_dots": "Dots are a sample, slowed down (cosmetic).",
    # the cluster picture: the topology under the grid
    "topology": "service → {a} and {b}",
    # the dependencies (toplist bars: at most 10 letters)
    "dep_payments": "Payments",
    "dep_recs": "Recs",
    # incidents
    "title": "{dep} slow",
    "slow": "{dep} is slow, {seconds:.0f} s a call: {cause}",
    "fast_again": "{dep} is fast again",
    "warn_busy": "all {workers} workers are busy",
    # the panel
    "tile_healthy": "Fine",
    "tile_fails": "Fails",
    "tile_workers": "Workers",
    "target_busy": "busy",
    "answers": "Answers",
    "head_both_fail": "{dep} is slow, and {healthy} fails too",
    "head_contained": "{dep} is slow; {healthy} is fine",
    "head_still_open": "{dep} is back; the breaker is still open",
    "head_back": "{dep} is back",
    "head_calm": "Both dependencies answer fast",
    "chart_limit": "{workers} workers",
    "note_chart": "The chart: busy workers each second.",
    # the relay picture: the breaker and bulkhead in our service, under it (at most ~14 letters)
    "relay_closed": "breaker closed",
    "relay_open": "breaker open",
    "relay_half_open": "half-open",
    "relay_bulkhead": "bulkhead full",
    "relay_full": "workers full",
    # errors in your code
    "stuck": "a request has been running for over {seconds:.0f} s: does Client.call wait for something that never finishes?",
}

LESSON = Lesson(
    title="Circuit breaker",
    one_liner="One slow dependency can hold every worker you have, and then everything fails.",
    learn=(
        "A slow dependency is worse than a dead one. A dead one fails fast; a slow one holds a "
        "worker (a thread, a connection, a slot) for every call. At 40 calls/s and 8 s a call, it "
        "wants 320 workers. With 24, the pool fills in a second, and requests that never touch the "
        "slow dependency queue behind it and fail: a cascading failure.",
        "Timeouts bound how long one call can hold a worker. They are necessary, but not enough: "
        "40 calls/s at a 1 s timeout still wants 40 workers.",
        "A bulkhead caps how many workers each dependency may hold (like the watertight walls in a "
        "ship's hull). The slow dependency can sink its own compartment, not the whole service.",
        "A circuit breaker notices the failures and stops calling for a while: calls fail at once "
        "instead of waiting for the timeout. After a cool-down it lets one probe through, and "
        "closes again when the dependency answers.",
    ),
    watch_for=(
        "No protection: the Workers tile hits 24/24 and the healthy dependency fails too.",
        "Timeouts: calls give up after 1 s, but the pool still fills while it is slow.",
        "Timeouts + bulkhead: the healthy dependency is fine; users of the slow one wait 1 s to fail.",
        "Timeouts + bulkhead + breaker: the door shuts, calls fail in under 1 ms, and it reopens after.",
    ),
    build=(
        ("Python: a timeout on every call",
         "async with asyncio.timeout(1.0):\n"
         "    return await client.get(url)"),
        ("resilience4j (Java): a breaker and a bulkhead around a call",
         "CircuitBreaker cb = CircuitBreaker.ofDefaults(\"recs\");\n"
         "Bulkhead bh = Bulkhead.of(\"recs\", BulkheadConfig.custom().maxConcurrentCalls(10).build());\n"
         "Supplier<Recs> call = Decorators.ofSupplier(recs::fetch)\n"
         "    .withCircuitBreaker(cb).withBulkhead(bh).decorate();"),
        ("Envoy: outlier detection and connection limits per cluster",
         "circuit_breakers:\n"
         "  thresholds: [{max_connections: 100, max_pending_requests: 50}]\n"
         "outlier_detection:\n"
         "  consecutive_5xx: 5\n"
         "  base_ejection_time: 30s"),
    ),
    checklist=(
        "Every outbound call has a timeout, shorter than the caller's own deadline.",
        "Each dependency gets its own pool or concurrency limit (a bulkhead).",
        "A breaker per dependency (or per host), with metrics on its state changes.",
        "A fallback for when the breaker is open: a cached answer, a default, or a clear error.",
        "Alert on breaker opens, and test them: slow a dependency down in staging.",
    ),
    refs=(
        Ref("Martin Fowler: CircuitBreaker",
            "https://martinfowler.com/bliki/CircuitBreaker.html",
            "The pattern, its three states, and a small implementation."),
        Ref("Azure Architecture Center: Circuit Breaker pattern",
            "https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker",
            "When to use it, the half-open state, and what to watch out for."),
        Ref("Azure Architecture Center: Bulkhead pattern",
            "https://learn.microsoft.com/en-us/azure/architecture/patterns/bulkhead",
            "Isolating resources per consumer or dependency so one failure stays contained."),
        Ref("resilience4j: CircuitBreaker",
            "https://resilience4j.readme.io/docs/circuitbreaker",
            "A production breaker: sliding windows, failure rate and slow-call thresholds."),
        Ref("Google SRE book: Addressing Cascading Failures",
            "https://sre.google/sre-book/addressing-cascading-failures/",
            "How resource exhaustion spreads, and the defences that stop it."),
    ),
    try_next=(
        "Do stage 1 in labs/circuit_breaker/main.py and watch the slow calls stop at 1 s.",
        "Do stage 2 and watch the healthy dependency keep its workers.",
        "Do stage 3 and watch the door shut while it is slow, then open again.",
        "Try --set workers=60: how much slowness can timeouts alone absorb?",
    ),
)

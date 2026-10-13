from core.lessons import Lesson, Ref

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

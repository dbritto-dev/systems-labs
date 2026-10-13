from core.lessons import Lesson, Ref

LESSON = Lesson(
    title="Overload & queues",
    one_liner="A short spike can leave a server busy forever, working for users who already left.",
    learn=(
        "A queue absorbs a burst, but every request in it waits for all the ones ahead. When the "
        "wait passes the user's timeout, the user gives up and retries, and the request they gave "
        "up on is still in the queue. The server now works on requests nobody wants.",
        "That is a metastable failure: the spike that started it is over, but the retries and the "
        "dead work keep the server overloaded. It stays broken until something sheds the load.",
        "Bound the queue: a request that would wait too long is rejected at the door. A fast no "
        "is an answer; a slow timeout is a retry.",
        "Drop work that is too late: carry the deadline with the request, and skip it when there "
        "is not enough time left to answer. Nothing is wasted on users who left.",
        "Adaptive LIFO: when the queue is long, serve the newest requests first. Those users are "
        "still waiting, so they get a quick reply, while the old ones expire and are dropped.",
    ),
    watch_for=(
        "Unbounded FIFO: the queue grows past thousands and the server goes orange (WASTING).",
        "Bounded queue: the door turns red and rejects, but the work is still for users who left.",
        "Skip late requests: nothing is wasted and it recovers, but replies take ~0.9 s.",
        "Adaptive LIFO: replies take milliseconds even at 2.5x the traffic.",
    ),
    build=(
        ("Go (net/http): give up early when the client is gone or the deadline is near",
         "select {\n"
         "case <-r.Context().Done():\n"
         "    return // the client left: do not do the work\n"
         "default:\n"
         "}\n"
         "if dl, ok := r.Context().Deadline(); ok && time.Until(dl) < 100*time.Millisecond {\n"
         "    http.Error(w, \"too late\", http.StatusServiceUnavailable)\n"
         "    return\n"
         "}"),
        ("gRPC: deadlines travel with the call",
         "stub.Get(request, timeout=1.0)  # the server sees the remaining time and can skip"),
        ("Envoy: shed load at the door",
         "circuit_breakers:\n"
         "  thresholds:\n"
         "  - max_pending_requests: 200   # a bounded queue: the rest get a fast 503"),
    ),
    checklist=(
        "Every queue has a bound, set in time (how long a request may wait), not just items.",
        "Deadlines are passed down, and work is skipped when not enough time is left.",
        "Rejections are fast and do not trigger retries (or retries spend a budget).",
        "Under overload, serve the newest requests first (adaptive LIFO) or use CoDel.",
        "Watch goodput (replies in time), not just throughput: a busy server can be useless.",
        "Test it: send 2-3x the traffic for 10 s, then check it recovers on its own.",
    ),
    refs=(
        Ref("AWS Builders' Library: Using load shedding to avoid overload",
            "https://aws.amazon.com/builders-library/using-load-shedding-to-avoid-overload/",
            "Goodput, wasted work, and shedding before it is too late."),
        Ref("AWS Builders' Library: Avoiding insurmountable queue backlogs",
            "https://aws.amazon.com/builders-library/avoiding-insurmountable-queue-backlogs/",
            "Why backlogs never drain on their own, and LIFO under load."),
        Ref("Metastable Failures in Distributed Systems (HotOS 2021)",
            "https://sigops.org/s/conferences/hotos/2021/papers/hotos21-s11-bronson.pdf",
            "The failure that keeps itself going after the trigger is gone."),
        Ref("Fail at Scale (Facebook, ACM Queue 2015)",
            "https://research.facebook.com/publications/fail-at-scale/",
            "Controlled delay (CoDel) and adaptive LIFO for queues under load."),
        Ref("Google SRE book: Handling Overload",
            "https://sre.google/sre-book/handling-overload/",
            "Client-side throttling and graceful degradation."),
    ),
    try_next=(
        "Do stage 1 in labs/overload/main.py and watch the door reject at the spike.",
        "Do stage 2 and watch the Waste goal turn green and the server recover.",
        "Do stage 3 and watch the reply time drop to milliseconds.",
        "Try --set rate=90: how close to capacity can it run before a spike breaks it?",
    ),
)

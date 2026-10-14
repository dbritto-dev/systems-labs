"""Lab deadline_propagation, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Deadline propagation"
SUMMARY = "Four services in a chain keep working after users give up. Pass the deadline down, skip late work."
PARAMS = {"rate": "user requests per second", "connections": "the db's connections (its pool)"}

INCIDENT = IncidentText("Slowdown", "the slowdown", "the next slowdown")
VERBS = {"slow": "SLOW", "fast": "FAST"}
CAUSES = {
    "slow_query": "a slow query plan after a deploy",
    "lock_contention": "lock contention on the orders table",
    "degraded_replica": "reads moved to a degraded replica",
    "gc_storm": "a GC storm on the database nodes",
    "vacuum": "a maintenance job saturating the disks",
    "cold_cache": "a cold buffer cache after a failover",
}

STAGES = [
    StageText("Per-hop timeouts",
              "Challenge: each hop waits its own 2 s, so it keeps waiting after the user has left.",
              "Stage 1: pass the deadline down (next_deadline)"),
    StageText("Deadline passed down",
              "Challenge: the hops give up in time, but the db still runs queries for users who left.",
              "Stage 2: skip work once expired()"),
    StageText("Deadline + skip late work",
              "Solved: the chain gives up with the user and never works for someone who has left.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "handle must return \"ok\""),
    "waste": GoalText("Wasted ≤ 5%", "skip work past the deadline"),
    "served": GoalText("Served ≥80% of max", "skip late work, fail fast"),
    "overrun": GoalText("Overrun p99 <10ms", "pass the deadline down"),
}

LEGEND = {"idle": "idle", "waiting": "waiting", "waiting_long": "waiting > 1 s", "served": "served",
          "failed": "failed", "abandoned": "left, still worked on", "incident": "incident"}

STRINGS = {
    "note_dots": "Dots are a sample, slowed down (cosmetic).",
    "note_chart": "The chart: db queries a second; red ones were for users who had left.",
    # the services (toplist bars: at most 10 letters)
    "hop_gateway": "Gateway",
    "hop_api": "API",
    "hop_orders": "Orders",
    "hop_db": "DB",
    # the state under the picture
    "state_dead": "{dead}/{n} for nobody",
    # incidents
    "title": "DB slow",
    "slow": "the db is slow, {ms:.0f} ms a query: {cause}",
    "fast_again": "the db is fast again",
    "warn_waste": "most db queries are for users who left",
    # the panel
    "tile_waste": "Wasted",
    "tile_served": "Served",
    "tile_overrun": "Overrun",
    "at_hops": "Requests",
    "at_hops_sub": "in each service now",
    "head_waste": "The db works for users who left",
    "head_slow": "The db is slow; no wasted work",
    "head_backlog": "The db is back; backlog draining",
    "head_back": "The db is fast again",
    "head_calm": "Every service answers fast",
    # errors in your code
    "stuck": "a request has held a worker for over {seconds:.0f} s: does handle wait for something that never finishes?",
}

LESSON = Lesson(
    title="Deadline propagation",
    one_liner="A user who gives up does not stop the work: only a deadline passed down the chain does.",
    learn=(
        "A request crosses several services: gateway → api → orders → db. The user gives up after "
        "2 s, but nothing tells the services. If each hop has its own 2 s timeout, counted from when "
        "IT called, the timeouts do not add up: a hop that got the request late (after a queue) "
        "keeps waiting long after the user has left, holding a worker.",
        "Worse, the bottom of the chain never hears that nobody is waiting. When the db slows down, "
        "a queue forms in front of it, and it runs every query in it, also for users who left "
        "seconds ago. That wasted work takes the capacity the live requests need, the queue grows, "
        "more users give up, and the slowdown feeds itself.",
        "Deadline propagation: the client sends an absolute deadline (when it stops waiting), and "
        "each hop passes it on minus a margin, so the next hop must be done a little before it must: "
        "its answer arrives in time, and work it starts just before its deadline can still finish. "
        "Every hop waits only as long as its caller does, and the whole chain gives up together.",
        "Knowing the deadline, a service can skip work nobody will see: check it before the "
        "expensive part (a query, a call to the next service) and fail fast if it has passed. The "
        "queue drains at once, and the db's time goes to users who are still there.",
    ),
    watch_for=(
        "Per-hop timeouts: Overrun reaches tens of ms to seconds; red rings (users who left) pile up.",
        "Deadline passed down: Overrun drops to 0, but the chart's red part (wasted queries) stays.",
        "Deadline + skip late work: no red on the chart, and Served stays near what the db can do.",
    ),
    build=(
        ("Go: the context carries the deadline to every call, the query included",
         "ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)\n"
         "defer cancel()\n"
         "if ctx.Err() != nil { return ctx.Err() }  // skip work nobody waits for\n"
         "rows, err := db.QueryContext(ctx, q)    // the db stops at the deadline too"),
        ("gRPC (Python): pass on what is left, minus a margin",
         "left = context.time_remaining() - 0.05\n"
         "if left <= 0:\n"
         "    context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, \"too late\")\n"
         "reply = orders_stub.Get(req, timeout=left)"),
        ("Envoy: the router tells the upstream how long it will wait",
         "route:\n"
         "  timeout: 2s\n"
         "# upstreams read x-envoy-expected-rq-timeout-ms and can give up early"),
    ),
    checklist=(
        "The edge (gateway or client) sets one deadline per request, close to what users will wait.",
        "Every hop passes the deadline on (gRPC does it for you), minus a small margin.",
        "Every outbound call and every query uses the time left, never a fixed timeout of its own.",
        "Check the deadline before expensive work and before each call; fail fast if it has passed.",
        "Measure work done after the deadline (wasted work); it should be near zero.",
    ),
    refs=(
        Ref("gRPC: Deadlines",
            "https://grpc.io/docs/guides/deadlines/",
            "Setting a deadline on the client, checking it on the server, and propagating it."),
        Ref("gRPC blog: gRPC and Deadlines",
            "https://grpc.io/blog/deadlines/",
            "Why every call needs a deadline, and how servers should check it."),
        Ref("Google SRE book: Addressing Cascading Failures",
            "https://sre.google/sre-book/addressing-cascading-failures/",
            "Deadline propagation, missing deadlines, and work done for requests nobody waits for."),
        Ref("AWS Builders' Library: Using load shedding to avoid overload",
            "https://aws.amazon.com/builders-library/using-load-shedding-to-avoid-overload/",
            "Timeout hints from clients, and skipping work for requests that have already timed out."),
        Ref("Go: package context",
            "https://pkg.go.dev/context",
            "Deadlines and cancellation carried across API boundaries and goroutines."),
    ),
    try_next=(
        "Do stage 1 in labs/deadline_propagation/main.py and watch Overrun drop to 0.",
        "Do stage 2 and watch the red queries vanish from the chart.",
        "Try --set connections=6: with enough db capacity, does any of this still matter?",
        "Set MARGIN = 0.0 in your file: why do served requests drop?",
    ),
)

"""Lab overload, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Overload & queues"
SUMMARY = "A spike fills the queue with users who already left. Shed load so the server recovers."
PARAMS = {"rate": "users per second (each waits 1 s, then retries up to twice)"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"spike": "SPIKE", "calm": "CALM", "drop": "DROP", "up": "UP"}
CAUSES = {
    "viral_post": "a post went viral",
    "thundering_herd": "a thundering herd after a deploy",
    "early_batch": "a partner's batch job started early",
    "app_retry_storm": "a retry storm from a mobile app release",
    "cache_flushed": "a cache in front of it was flushed",
    "node_lost": "one of its nodes was lost",
    "noisy_neighbour": "a noisy neighbour is starving the CPU",
    "bad_config": "a bad config halved the workers",
    "gc_pauses": "garbage collection pauses",
}

STAGES = [
    StageText("Unbounded FIFO",
              "Challenge: after a spike the queue fills with users who left, and it never recovers.",
              "Stage 1: reject at the door when the queue is full"),
    StageText("Bounded queue",
              "Challenge: the queue is bounded, but the server still works for users who already left.",
              "Stage 2: skip requests that are too late to answer"),
    StageText("Skip late requests",
              "Challenge: no wasted work, but every reply arrives just before users give up. Serve fresh.",
              "Stage 3: newest first while the queue is long"),
    StageText("Adaptive LIFO",
              "Solved: the queue is bounded, nothing is wasted, and the newest users get quick replies.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "answer users in time"),
    "queue": GoalText("Queue ≤ 250", "reject when queue is full"),
    "waste": GoalText("Waste < 5%", "skip requests too late"),
    "goodput": GoalText("Goodput ≥ 80%", "stop serving gone users"),
    "fast": GoalText("Fast < 300ms", "newest first when long"),
    "recovered": GoalText("Recovered ≤ 5 s", "shed load to recover"),
}

LEGEND = {"idle": "idle", "first_try": "first try", "retries": "retry 1,2", "wasted": "work for users who left",
          "rejected": "rejected", "in_time": "in time", "max": "max", "incident": "incident"}

STRINGS = {
    # the cluster picture: the topology under the grid
    "topology": "queue → server",
    # incidents
    "capacity_drop": "Capacity drop",
    "spike": "Spike",
    "back_to_normal": "is back to normal",
    "capacity_down": "is down to {share:.0%} capacity: {cause}",
    "traffic_up": "is getting {factor:.1f}x the traffic: {cause}",
    "warn_queue": "queue passed {limit}",
    "warn_waste": "{share:.0%} of work wasted",
    # goal values
    "seconds": "{seconds:.0f} s",
    "over_seconds": ">{seconds:.0f} s",
    # the panel
    "tile_served": "Served",
    "tile_waste": "Waste",
    "tile_reply": "Reply",
    "bar_arrive": "Arrive",
    "bar_server": "Server",
    "bar_rejected": "Rejected",
    "toplist": "Requests",
    "max": "max {limit:.0f}/s",
    "head_wasted": "{share:.0%} of the work is for users who left",
    "head_capacity": "Capacity down to {capacity:.0f}/s; {waiting} waiting",
    "head_rejecting": "Extra requests are rejected at the door",
    "head_ok": "Every reply arrives in time",
    "stat_gave_up": "gave up",
    "stat_rejected": "rejected",
    "note_dots": "Dots: a sample, slowed down (cosmetic).",
    # the picture
    "state_wasting": "WASTING",
    # errors in your code
    "stuck": "a user has been waiting for over {seconds:.0f} s",
}

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

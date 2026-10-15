"""Lab async_backpressure, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Async backpressure"
SUMMARY = "An asyncio pipeline from a firehose to a database. Keep memory bounded when a stage is slow."
PARAMS = {"rate": "events per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"slow": "SLOW", "spike": "SPIKE", "burst": "BURST", "outage": "DOWN", "calm": "CALM"}
CAUSES = {
    "vacuum": "autovacuum on the events table: every insert waits on I/O",
    "compaction": "the database compacts its storage: writes slow to a crawl",
    "throttled": "the database throttles us: we went over our provisioned writes",
    "backup": "a nightly backup saturates the database's disks",
    "gc_pause": "the enrichment service is stuck in long GC pauses",
    "cold_cache": "the enrichment service was redeployed: its cache is cold",
    "db_failover": "the enrichment service's database is failing over",
    "noisy_neighbour": "a noisy neighbour on the enrichment service's hosts",
    "backfill": "the upstream backfills yesterday's events",
    "viral": "a post goes viral: clicks pour in",
    "replay": "the upstream replays what it held during its own outage",
    "campaign": "a marketing campaign goes out to every user at once",
    "failover": "the database fails over to its replica",
    "proxy_restart": "the database proxy restarts after a config push",
    "network": "a network partition between us and the database",
    "cert_expired": "the database's TLS certificate expired until it was renewed",
}

STAGES = [
    StageText("Unbounded queues",
              "Challenge: a slow sink grows the queues until the OOM kill loses everything held.",
              "Stage 1: bounded queues: Queue(maxsize=QUEUE_SIZE)"),
    StageText("Bounded queues",
              "Challenge: no OOM, but the stalled source overflows the upstream and small batches lag.",
              "Stage 2: credits, adaptive batches, shed LOW"),
    StageText("Credits + adaptive batches",
              "Solved: memory bounded, LOW shed and counted, HIGH all written, batches grow with the lag.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "Pipeline.run() must write"),
    "oom": GoalText("OOM kills = 0", "bound the queues"),
    "lost": GoalText("Lost = 0", "shed LOW, count every drop"),
    "peak": GoalText("Peak mem ≤ 80%", "credits bound every stage"),
    "throughput": GoalText("Throughput ≥ 80%", "batch what is queued"),
    "p99": GoalText("p99 after < 1s", "bounded windows, fast drain"),
}

LEGEND = {"idle": "idle", "event": "event", "waiting": "waited 0.25,1,4s", "written": "written",
          "shed": "shed (LOW)", "lost": "lost", "limit": "80% memory", "incident": "incident"}

STRINGS = {
    # incidents
    "title_slow": "Slow sink",
    "title_spike": "Spike",
    "title_burst": "Burst",
    "title_outage": "Sink down",
    "slow_start": "the sink is {n:.0f}x slower: {cause}",
    "slow_end": "the sink is back to normal speed",
    "spike_start": "enrichment calls take {n:.0f}x longer: {cause}",
    "spike_end": "the enrichment service is fast again",
    "burst_start": "the upstream sends {n:.1f}x the events: {cause}",
    "burst_end": "the upstream is back to its usual rate",
    "outage_start": "the sink is down, every write fails: {cause}",
    "outage_end": "the sink is back",
    "warn_oom": "{n} OOM kill(s): {lost:,} events lost with the process",
    "warn_upstream": "{n:,} events dropped by the upstream: its buffer was full",
    "warn_shed": "{n:,} LOW events shed (counted)",
    # goal values
    "count": "{n:,}",
    # the panel
    "tile_memory": "Memory",
    "tile_lost": "Lost",
    "bar_arrived": "Arrived",
    "bar_written": "Written",
    "bar_dropped": "Shed/lost",
    "limit": "can take {n}/s",
    "title": "Events",
    "subtitle": "per second, last 3 s",
    "head_restarting": "OOM kill: {n:,} events lost",
    "head_upstream": "Upstream full: {n:,} events lost",
    "head_memory": "Memory {pct}: queues still grow",
    "head_shed": "Shed {n:,.0f} LOW/s, counted",
    "head_paused": "Paused: {n:,} wait upstream",
    "head_slow": "Sink slow: batches should grow",
    "head_spike": "Enrichment slow: stages wait",
    "head_burst": "The upstream sends more",
    "head_outage": "Sink down: writes retried",
    "head_ok": "Writes of ~{n:,} events",
    "stat_written": "written",
    "stat_lost": "lost",
    "stat_shed": "shed",
    "note_chart": "Chart: memory, % of 256 MiB: runtime, raw, parsed, enriched.",
    # the pictures
    "state_restarting": "OOM KILLED",
    "state_memory": "MEMORY HIGH",
    "state_lost": "EVENTS LOST",
    "state_shed": "SHEDDING",
    "state_paused": "PAUSED",
    "state_slow": "SINK SLOW",
    "state_spike": "SLOW ENRICH",
    "state_burst": "BURST",
    "state_outage": "SINK DOWN",
    "pic_mem": "{state} · {pct}",
    "lbl_in": "in {n}",
    "lbl_a": "A {n}",
    "lbl_b": "B {n}",
    "lbl_c": "C {n}",
    "lbl_down": "DOWN",
    "lbl_slow": "{n:.0f}x slow",
    "lbl_rate": "{n}/s",
    "lbl_sink": "sink {state}",
    "lbl_sink_tiny": "sink",
    "pic_state": "memory {pct} · {state}",
    # errors in your code
    "returned": "Pipeline.run() returned: it must run forever (await the stages in a TaskGroup)",
}

LESSON = Lesson(
    title="Backpressure in an asyncio pipeline",
    one_liner="A fast producer and a slow consumer need a limit between them, or memory becomes the limit.",
    learn=(
        "An asyncio.Queue() has no limit. When the stage after it is slower than the one before it, "
        "the queue grows: a slow database, a slow service or a burst turns into memory, and memory "
        "has a hard limit. Past it the kernel OOM-kills the process and everything in it is gone, "
        "with nobody told which events.",
        "Backpressure is the slow stage pushing back: give each queue a maxsize and `put` waits while "
        "it is full. The wait travels back stage by stage to the source, which stops reading. Memory "
        "is bounded, but now the upstream holds the backlog. A durable log (Kafka) can wait; a push "
        "firehose has a small buffer and drops what does not fit. Decide what happens at the source.",
        "Credits make the window explicit: each stage grants the one before it a number of events it "
        "may send, and grants them back only once the events have moved on. That bounds the events "
        "in the queue and in the hands of the next stage (the batch being written, the calls in "
        "flight), and the source can see when it is short instead of just blocking.",
        "Batch what is queued. A write costs a fixed overhead plus a little per event; a fixed batch "
        "of 50 wastes a slow sink on overhead. Take one item, then everything already waiting, up to "
        "the maximum: batches stay small when the sink is fast and grow when it is slow (smart batching).",
        "When even full batches cannot keep up, something must give: choose it. Shed the low-priority "
        "class, counted and visible, and keep a reserve of the window for the high-priority one. "
        "A drop you count is a decision; a drop in an OOM kill or an upstream overflow is an incident.",
    ),
    watch_for=(
        "Unbounded queues: during the slow sink the memory climbs (orange in the chart) until the OOM "
        "kill; ~10,000 events vanish, the process restarts, and it happens again.",
        "Bounded queues: the memory stays flat, but the door closes (the source stops reading), the "
        "events wait upstream (deep orange) and red ones are lost when its buffer overflows.",
        "Credits: grey LOW events are shed at the door, every HIGH event is written, batches of 1,000.",
    ),
    build=(
        ("Python: a bounded queue blocks the producer",
         "queue = asyncio.Queue(maxsize=100)\n"
         "await queue.put(item)    # waits while 100 items are queued\n"
         "queue.put_nowait(item)   # raises asyncio.QueueFull instead"),
        ("Python: credits (a semaphore for n permits)",
         "await credits.take(len(chunk))   # the window has room\n"
         "next_queue.put_nowait(chunk)\n"
         "...                              # downstream, once it moved on:\n"
         "credits.grant(len(chunk))"),
        ("Python: adaptive batching",
         "batch = list(await queue.get())\n"
         "while len(batch) < MAX_BATCH and not queue.empty():\n"
         "    batch += queue.get_nowait()\n"
         "await sink.write(batch)"),
        ("Kafka consumer: pause instead of buffering",
         "consumer.pause(partitions)    # stop fetching, keep the group membership\n"
         "consumer.resume(partitions)   # when the window has room again"),
    ),
    checklist=(
        "Every queue between two stages has a bound, in items or better in bytes.",
        "The bound counts what a stage holds in flight too, not just what waits in the queue.",
        "Peak memory with every queue full is under the container's limit, with headroom.",
        "The source has a policy when it is full: pause (if the upstream can hold it) or shed.",
        "Shedding is by priority and counted; nothing is lost without a metric.",
        "Batches grow with the backlog, up to the sink's maximum.",
        "Queue depth per stage is a metric, so you can see which stage is slow.",
    ),
    refs=(
        Ref("Armin Ronacher: I'm not feeling the async pressure",
            "https://lucumr.pocoo.org/2020/1/1/async-pressure/",
            "Why asyncio code without backpressure falls over, and where the buffers hide."),
        Ref("Python: asyncio queues",
            "https://docs.python.org/3/library/asyncio-queue.html",
            "maxsize, put() that waits while the queue is full, put_nowait() and QueueFull."),
        Ref("Reactive Streams",
            "https://www.reactive-streams.org/",
            "Demand-driven flow control: the subscriber asks for n items with request(n)."),
        Ref("Martin Thompson: Smart batching",
            "https://mechanical-sympathy.blogspot.com/2011/10/smart-batching.html",
            "Batch whatever is waiting: small batches when idle, big ones under load."),
        Ref("Fred Hébert: Queues don't fix overload",
            "https://ferd.ca/queues-don-t-fix-overload.html",
            "A queue only delays the overload; bound it and push back or drop."),
        Ref("Google SRE book: Handling overload",
            "https://sre.google/sre-book/handling-overload/",
            "Criticality: shed the least important work first, and count it."),
        Ref("Node.js: Backpressuring in streams",
            "https://nodejs.org/en/learn/modules/backpressuring-in-streams",
            "The same idea in another runtime: highWaterMark and write() returning false."),
    ),
    try_next=(
        "Do stage 1 in labs/async_backpressure/main.py and watch the OOM kill go away; then watch the door.",
        "Then watch the first incident's end: how many events did the upstream drop?",
        "Do stage 2, then try --seed 5: a sink outage at 1:57, then enrichment spikes.",
    ),
)

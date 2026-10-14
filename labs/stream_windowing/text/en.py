"""Lab stream_windowing, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Stream windowing"
SUMMARY = "Count purchases per 10 s window while events arrive late and out of order: event time, watermarks, lateness."
PARAMS = {"rate": "purchases (events) per second"}

INCIDENT = IncidentText("Late data", "the late data", "the next late data")
VERBS = {"offline": "BATCH", "lag": "LAG", "skew": "SKEW", "backfill": "REPLAY", "calm": "CALM"}
CAUSES = {
    # phones back online
    "subway": "riders come out of the subway and their phones sync",
    "flight_mode": "phones leave flight mode after landing",
    "app_suspended": "the OS had suspended the app; it flushes its queue",
    "carrier_outage": "a mobile carrier outage ends",
    # a partition lags
    "broker_gc": "a long GC pause on the partition's broker",
    "slow_disk": "a slow disk on the partition's leader",
    "rebalance": "a consumer group rebalance",
    "hot_partition": "a hot key floods the partition",
    # a producer's clock is behind
    "ntp_down": "NTP is unreachable from one producer fleet",
    "vm_resume": "VMs resumed from a pause with a stale clock",
    "bad_rtc": "a batch of devices with a bad hardware clock",
    "container_clock": "a container image ships a wrong time zone setup",
    # a backfill
    "replay": "a replay of events lost by an upstream bug",
    "partner_upload": "a partner uploads its sales from the last minutes",
    "mirror_catchup": "a mirror from another region catches up",
    "restore": "events restored from the archive after an outage",
}

STAGES = [
    StageText("Processing time",
              "Challenge: windows count events when they arrive, so late ones land in the wrong window.",
              "Stage 1: event time with a watermark"),
    StageText("Event time + watermark",
              "Challenge: calm windows are right, but late events are dropped after the window closes.",
              "Stage 2: allowed lateness, updates, side output"),
    StageText("Allowed lateness + updates",
              "Solved: late events correct their window; later ones go to the side output.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Calm windows ≥99.9%", "count by event time"),
    "exact": GoalText("Exact windows ≥99%", "keep windows, emit updates"),
    "dropped": GoalText("Dropped = 0", "side output, never drop"),
    "latency": GoalText("Latency p99 ≤5s", "emit at the watermark"),
    "state": GoalText("State ≤ 6 windows", "evict past the lateness"),
}

LEGEND = {"idle": "idle", "on_time": "on time", "late": "late (more = later)", "counted": "counted",
          "updated": "counted late (update)", "side": "side output", "dropped": "dropped / wrong window",
          "incident": "incident"}

STRINGS = {
    "note_dots": "Dots are a sample, slowed down (cosmetic).",
    "note_chart": "The chart: events a second by what the processor did with them.",
    # incidents
    "title_offline": "Late batch",
    "title_lag": "Partition lag",
    "title_skew": "Clock skew",
    "title_backfill": "Backfill",
    "offline_start": "phones send events up to {seconds:.0f} s old: {cause}",
    "offline_end": "the offline batches are in",
    "lag_start": "partition {partition} lags {seconds:.0f} s behind: {cause}",
    "lag_end": "the partition has caught up",
    "skew_start": "a producer's clock is {seconds:.0f} s behind: {cause}",
    "skew_end": "the clock is right again",
    "backfill_start": "a backfill sends events up to {minutes:.0f} min old: {cause}",
    "backfill_end": "the backfill is done",
    "warn_dropped": "{n} late events were dropped",
    "warn_wrong": "{n} events were counted in the wrong window",
    # the state under the picture
    "state": "watermark {wm} · state {n}/{max}",
    "state_none": "no events yet",
    # the panel
    "tile_exact": "Exact",
    "tile_dropped": "Dropped",
    "tile_latency": "Latency",
    "bars": "Windows",
    "bars_sub": "events by event time",
    "head_dropped": "Late events are dropped",
    "head_wrong": "Late events land in wrong windows",
    "head_side": "Too-late events go to side output",
    "head_updated": "Late events update closed windows",
    "head_state": "The state keeps growing",
    "head_offline": "A late batch is arriving",
    "head_lag": "A partition is lagging",
    "head_skew": "A producer's clock is behind",
    "head_backfill": "A backfill replays old events",
    "head_edges": "Stragglers land a window late",
    "head_calm": "Events arrive on time",
    "stat_counted": "counted",
    "stat_updates": "updates",
    "stat_side": "side",
    "stat_dropped": "dropped",
    "stat_late": "delay p99",
}

LESSON = Lesson(
    title="Stream windowing",
    one_liner="Count by when things happened, wait a little, and keep correcting: a watermark plus allowed lateness.",
    learn=(
        "A stream processor counts purchases per 10-second window for a live dashboard. Each "
        "event carries its event time (when the purchase happened); it reaches the processor "
        "later, through a log with partitions: normally within a second and a little out of "
        "order, but sometimes much later (phones that were offline, a lagging partition, a "
        "producer whose clock is behind, a backfill).",
        "Processing time, the window open when an event ARRIVES, is easy and fast but wrong: a "
        "straggler near a window's end lands in the next one, and a late batch lands all of it "
        "in the current window. The totals per window are wrong exactly when it matters.",
        "Event time with a watermark: put each event in the window of its own timestamp, and "
        "decide when a window is complete with a watermark, the largest event time seen minus a "
        "bound on the disorder (2 s here). When the watermark passes a window's end, emit it. "
        "Events behind the watermark are late: dropping them keeps windows small and results "
        "fast, but silently loses data.",
        "Allowed lateness: keep each closed window a while longer (30 s of watermark time) and, "
        "when a late event lands in it, emit the corrected count: the dashboard shows an update. "
        "Events later than that go to a side output (a dead-letter topic) for a batch job to "
        "reconcile, so nothing is dropped silently, and windows past their lateness are evicted, "
        "so the state stays bounded. Waiting longer before the first result would also be "
        "correct, but too slow for a live dashboard.",
    ),
    watch_for=(
        "Processing time: red at the door even in calm times (stragglers), and a lot of it in a late batch.",
        "Event time + watermark: calm windows are exact, but a late batch slams the door: red, dropped.",
        "Allowed lateness: late events turn blue (updates), very old ones purple (side output); the gauge stays low.",
    ),
    build=(
        ("Flink: a bounded-disorder watermark, allowed lateness and a side output for later events",
         "events.assignTimestampsAndWatermarks(\n"
         "    WatermarkStrategy.<Purchase>forBoundedOutOfOrderness(Duration.ofSeconds(2))\n"
         "        .withTimestampAssigner((p, ts) -> p.eventTime))\n"
         "  .keyBy(p -> p.shop)\n"
         "  .window(TumblingEventTimeWindows.of(Duration.ofSeconds(10)))\n"
         "  .allowedLateness(Duration.ofSeconds(30))\n"
         "  .sideOutputLateData(tooLate)\n"
         "  .aggregate(new CountPurchases());"),
        ("Kafka Streams: a grace period; late records update the window's count downstream",
         "purchases.groupByKey()\n"
         "  .windowedBy(TimeWindows.ofSizeAndGrace(Duration.ofSeconds(10), Duration.ofSeconds(30)))\n"
         "  .count();"),
        ("Spark Structured Streaming: the watermark bounds the state; update mode re-emits windows",
         "(events.withWatermark(\"event_time\", \"30 seconds\")\n"
         "   .groupBy(window(\"event_time\", \"10 seconds\")).count()\n"
         "   .writeStream.outputMode(\"update\"))"),
    ),
    checklist=(
        "Window by event time, never by arrival time, for anything you report or bill.",
        "Set the watermark from the disorder you measure (p99 of arrival minus event time), not a guess.",
        "Allow lateness for the delays you expect, and make the sink accept updates (upsert by window).",
        "Send events later than that to a side output and alert on its rate: never drop them silently.",
        "Evict windows past their lateness, and watch state size and the time to the first result.",
    ),
    refs=(
        Ref("Apache Flink: Timely Stream Processing",
            "https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/time/",
            "Event time, processing time, and watermarks."),
        Ref("Apache Flink: Windows",
            "https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/operators/windows/",
            "Tumbling windows, allowed lateness, and getting late data as a side output."),
        Ref("The Dataflow Model (VLDB 2015)",
            "https://www.vldb.org/pvldb/vol8/p1792-Akidau.pdf",
            "The paper behind watermarks, triggers and accumulating updates for late data."),
        Ref("Apache Beam: Watermarks and late data",
            "https://beam.apache.org/documentation/programming-guide/#watermarks-and-late-data",
            "Watermarks, allowed lateness and triggers that fire again for late data."),
        Ref("Spark Structured Streaming: Handling late data and watermarking",
            "https://spark.apache.org/docs/latest/streaming/apis-on-dataframes-and-datasets.html",
            "withWatermark, window aggregations, and how the watermark bounds the state."),
        Ref("Confluent: Kafka Streams concepts",
            "https://docs.confluent.io/platform/current/streams/concepts.html",
            "Event time, windowing, and grace periods for out-of-order records."),
    ),
    try_next=(
        "Do stage 1 in labs/stream_windowing/main.py and watch the calm windows turn exact.",
        "Do stage 2 and watch late events turn blue (updates) instead of red.",
        "Set ALLOWED_DELAY = 32.0 instead of allowing lateness: why does Latency fail?",
        "Skip evict() in stage 2: what happens to the gauge, and to State?",
    ),
)

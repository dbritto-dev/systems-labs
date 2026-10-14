"""Lab hedged_requests, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Hedged requests"
SUMMARY = "Rare slow replies set the p99. Send a second copy when the first is slow, within a budget."
PARAMS = {"rate": "user reads per second"}

INCIDENT = IncidentText("Slowdown", "the slowdown", "the next slowdown")
VERBS = {"slow": "SLOW", "fast": "FAST"}
CAUSES = {
    "compaction": "a compaction rewriting its files",
    "noisy_neighbour": "a noisy neighbour on its host",
    "degraded_volume": "a degraded disk volume",
    "backup_snapshot": "a backup snapshot reading its disk",
    "index_rebuild": "an index rebuild",
    "hot_key": "a hot key that every user reads",
    "cold_caches": "cold caches after a deploy",
    "slow_storage": "slow shared storage",
    "zone_congestion": "a congested network between zones",
}

STAGES = [
    StageText("One call",
              "Challenge: 1 reply in 50 is slow, and that sets the p99. Send a copy when it is slow.",
              "Stage 1: hedge after HEDGE_AFTER in Client.read"),
    StageText("Hedge",
              "Challenge: the tail is gone, but a slow replica costs a copy per read. Cap and cancel.",
              "Stage 2: a HedgeBudget, and cancel the loser"),
    StageText("Hedge + budget + cancel",
              "Solved: copies hide the rare slow reply, for a few % more load and no wasted work.",
              "All stages done"),
]

GOALS = {
    "tail": GoalText("p99 ≤ 50ms", "hedge after HEDGE_AFTER"),
    "extra": GoalText("Extra ≤ 10%", "spend a HedgeBudget token"),
    "waste": GoalText("Wasted ≤ 5%", "cancel the losing call"),
    "served": GoalText("Served ≥ 99%", "return the first answer"),
    "back": GoalText("Back p99 ≤ 50ms", "the budget must refill"),
}

LEGEND = {"idle": "idle", "first_call": "first call", "slow_reply": "slow reply", "copy": "copy (hedge)",
          "wasted": "loser still running", "failed": "failed", "served": "served", "limit": "10% extra",
          "incident": "incident"}

STRINGS = {
    "note_dots": "Dots are a sample, slowed down (cosmetic).",
    "note_chart": "The chart: copies sent each second.",
    # the cluster picture: the topology under the grid
    "topology": "service → {n} replicas",
    # a replica's name (toplist bars: at most 10 letters)
    "replica": "Replica {n}",
    # incidents
    "title_one": "{replica} slow",
    "title_all": "All slow",
    "slow_one": "{replica} is slow, {ms} a reply: {cause}",
    "fast_one": "{replica} is fast again",
    "slow_all": "every replica is slow, {ms} a reply: {cause}",
    "fast_all": "every replica is fast again",
    "warn_extra": "copies add {extra:.0%} load",
    # the panel
    "tile_extra": "Extra",
    "tile_waste": "Wasted",
    "head_all_storm": "All slow: copies add +{extra:.0%} load",
    "head_all_capped": "All slow: the budget caps copies",
    "head_one_hidden": "{replica} slow: copies cost +{extra:.0%}",
    "head_one_capped": "{replica} slow: copies capped",
    "head_one_waits": "{replica} slow: its readers wait",
    "head_back": "Fast again; slow reads finish",
    "head_tail": "Rare slow replies: p99 {p99}",
    "head_hedged": "Copies hide the tail: p99 {p99}",
    "head_calm": "Replies are fast",
    "chart_limit": "{extra:.0%} extra",
    # errors in your code
    "stuck": "a read has been running for over {seconds:.0f} s: does Client.read wait for something that never finishes?",
}

LESSON = Lesson(
    title="Hedged requests",
    one_liner="The p99 is set by rare slow replies; a second copy, sent late and on a budget, hides them.",
    learn=(
        "Most replies take ~10 ms, but about 1 in 50 takes 100-400 ms: a GC pause, a cache miss, a "
        "slow disk. That is rare for one call and common for users: the p99 IS that slow reply. At "
        "scale a page fans out to many servers, and almost every page meets one (Dean and Barroso, "
        "\"The Tail at Scale\").",
        "A hedged request waits a little (about the p95 of a reply), and if there is no answer yet, "
        "sends the same read to another replica and takes whichever answers first. Two slow replies "
        "in a row are very rare (1 in 2,500), so the p99 drops to ~30 ms. Only the slow ~2% get a "
        "copy, so it costs ~2% more load.",
        "Unbounded, it backfires exactly when things go wrong. When one replica is slow, every read "
        "sent to it gets a copy: +33% load. When every replica is slow, every read gets one: twice "
        "the load on a fleet that is already struggling. A hedge budget (like a retry budget) "
        "allows copies for at most ~5% of reads; past that, reads just wait.",
        "Cancel the loser. Once one copy has answered, the other is work nobody needs: a slow "
        "replica keeps it for its full half second, on a disk or a queue already too busy.",
        "Hedging hides short, random slowness. A replica that stays slow is a different problem: "
        "take it out of rotation for a while (the paper calls it probation; Envoy calls it outlier "
        "detection).",
    ),
    watch_for=(
        "One call: the p99 tile is red even with nothing wrong: a few rare slow replies set it.",
        "Hedge: orange copies fly to another replica; p99 ~30 ms, but Extra is +35% when a replica is slow.",
        "Hedge: deep orange losers pile up by the slow replica, still running: the Wasted tile.",
        "Hedge + budget + cancel: copies stay at a few %; in lanes (v) the door shuts while the budget is spent.",
    ),
    build=(
        ("Go: hedge a read, cancel the loser",
         "res := make(chan Result, 2) // room for both: the loser never blocks\n"
         "ctx, cancel := context.WithCancel(ctx)\n"
         "defer cancel() // the losing call stops\n"
         "go func() { res <- replicaA.Get(ctx, key) }()\n"
         "select {\n"
         "case r := <-res: return r\n"
         "case <-time.After(20 * time.Millisecond): // ~p95: send a copy\n"
         "    go func() { res <- replicaB.Get(ctx, key) }()\n"
         "}\n"
         "return <-res"),
        ("gRPC service config: a hedging policy with throttling",
         "\"hedgingPolicy\": {\"maxAttempts\": 2, \"hedgingDelay\": \"0.02s\"},\n"
         "\"retryThrottling\": {\"maxTokens\": 10, \"tokenRatio\": 0.1}"),
        ("Envoy: hedge on per-try timeout",
         "hedge_policy: {hedge_on_per_try_timeout: true}\n"
         "retry_policy: {per_try_timeout: 0.02s, num_retries: 1}"),
    ),
    checklist=(
        "Hedge only idempotent reads (or writes with an idempotency key).",
        "Set the hedge delay from measured latency (about the p95), not a guess.",
        "Cap copies with a budget or token bucket shared by the whole client.",
        "Cancel the losing call, and make the server stop work when it is cancelled.",
        "Measure copies sent per request; alert when it climbs.",
        "Pair it with outlier detection, so a replica that stays slow is taken out.",
    ),
    refs=(
        Ref("Dean and Barroso: The Tail at Scale (CACM 2013)",
            "https://research.google/pubs/the-tail-at-scale/",
            "Why rare slow replies dominate at scale, and hedged and tied requests."),
        Ref("The Tail at Scale (PDF)",
            "https://www.barroso.org/publications/TheTailAtScale.pdf",
            "The paper: a copy after 10 ms cut a p99.9 from 1,800 ms to 74 ms, for 2% more requests."),
        Ref("gRPC: Request Hedging",
            "https://grpc.io/docs/guides/request-hedging/",
            "hedgingDelay, maxAttempts, and throttling with tokens."),
        Ref("gRFC A6: gRPC client retries and hedging",
            "https://github.com/grpc/proposal/blob/master/A6-client-retries.md",
            "The design: the hedging policy and the token-bucket throttle that caps it."),
        Ref("Marc Brooker: Tail Latency Might Matter More Than You Think",
            "https://brooker.co.za/blog/2021/04/19/latency.html",
            "How fan-out turns a rare slow reply into a common slow request."),
        Ref("Finagle: MethodBuilder (backup requests)",
            "https://twitter.github.io/finagle/guide/MethodBuilder.html",
            "Backup requests in production: sent at a percentile, capped at a share of traffic."),
    ),
    try_next=(
        "Do stage 1 in labs/hedged_requests/main.py and watch the p99 tile turn green.",
        "Wait for a slow replica: watch Extra climb past 30% and the losers pile up by it.",
        "Do stage 2 and watch the copies stay at a few %, and the losers vanish.",
        "Try --set rate=300: does the budget still cap the copies?",
    ),
)

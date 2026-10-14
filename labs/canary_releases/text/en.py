"""Lab canary_releases, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Canary releases"
SUMMARY = "Ship new builds safely. A fixed canary first, then a staged one compared with the baseline."
PARAMS = {"rate": "user requests per second (it drifts ±15%)"}

INCIDENT = IncidentText("Release", "the release", "the next release")
VERBS = {"deploy": "DEPLOY", "close": "CLOSE", "step": "RAMP", "full": "FULL", "rollback": "UNDO",
         "cancel": "CANCEL", "manual": "MANUAL"}
CAUSES = {
    # good builds: what they change
    "copy_change": "new wording on the checkout page",
    "dependency_bump": "a library upgrade",
    "refactor": "a refactor of the search code",
    "flag_cleanup": "old feature flags removed",
    # a dependency flakes while a good build ships
    "db_failover": "the database fails over to its replica",
    "dns_blip": "the DNS resolver drops queries now and then",
    "provider_slow": "the payment provider has a bad minute",
    "cache_restart": "the shared cache restarts, node by node",
    # crash loops
    "missing_env": "it needs a setting that is not in production: it crash-loops",
    "bad_config": "a typo in its config: it crash-loops at start",
    "oom_start": "it runs out of memory at start: it crash-loops",
    "schema_mismatch": "it expects a column the database does not have yet: it crash-loops",
    # subtle error regressions
    "edge_case": "an unhandled edge case: ~3% of requests fail",
    "short_timeout": "a client timeout set too short: ~3% of requests fail",
    "retry_removed": "a retry removed by mistake: ~3% of requests fail",
    "serializer": "a new serializer chokes on some records: ~3% fail",
    # latency regressions
    "n_plus_one": "a new N+1 query: a quarter of requests get slower",
    "sync_logging": "synchronous logging on a hot path: a quarter of requests get slower",
    "cache_key": "a cache key bug: a quarter of requests miss the cache",
    "regex": "a regex that backtracks: a quarter of requests get slower",
    # bugs on one endpoint
    "currency_rounding": "a rounding change breaks payments in one currency (/pay)",
    "coupon_parser": "a coupon parser rejects valid coupons (/pay)",
    "tax_rule": "a new tax rule fails for some regions (/pay)",
    "card_validation": "stricter card validation rejects valid cards (/pay)",
}

STAGES = [
    StageText("Everywhere at once",
              "Challenge: every build goes to every user at once; a bad one hurts all of them.",
              "Stage 1: a 5% canary, a fixed error limit, a fixed bake"),
    StageText("Fixed canary",
              "Challenge: fixed rules let a slow build through and roll back good builds on noise.",
              "Stage 2: compare with the baseline; 5→25→50→100%"),
    StageText("Staged canary",
              "Solved: each step is compared with the baseline on enough samples; bad builds roll back.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "decide() must return 0 to 1"),
    "hurt": GoalText("Hurt ≤ 0.5%", "start small: a 5% canary"),
    "full": GoalText("Bad at 100% = 0", "compare errors AND latency"),
    "alarms": GoalText("False alarms = 0", "compare with the baseline"),
    "rollout": GoalText("Rollout ≤ 90s", "ramp 5→25→50→100%"),
}

LEGEND = {"idle": "idle", "request": "request", "waits": "waits", "served": "served", "failed": "failed",
          "live": "live build", "canary": "new build (canary)", "slow": "slow answer", "incident": "release"}

STRINGS = {
    "note_dots": "Dots are a sample, slowed down (cosmetic).",
    "note_chart": "The chart: requests each second, by the build that answered them, slow or failed on top.",
    # the pictures
    "state_live": "LIVE v{v}",
    "state_canary": "CANARY v{v} {w:.0%}",
    "state_bad": "BAD BUILD LIVE v{v}",
    "state_back": "ROLLED BACK v{v}",
    "cluster_live": "{state}  · v{v} on all {n} instances",
    "cluster_canary": "{state} on {b} of {n} · v{live} on {a}",
    # releases
    "good": "Good build",
    "flaky": "Flaky dependency",
    "crash": "Crash loop",
    "errors": "Error regression",
    "latency": "Slow build",
    "segment": "Bug on /pay",
    "good_start": "v{v} ships, a good build: {cause}",
    "flaky_start": "v{v} ships, a good build; meanwhile {cause}",
    "bad_start": "v{v} ships: {cause}",
    "release_end": "the release window of v{v} closes",
    "ev_step": "v{v} gets {w:.0%} of the traffic",
    "ev_full": "v{v} is live everywhere",
    "ev_full_bad": "v{v} is live everywhere, and it is bad: every user gets it",
    "ev_caught": "v{v} rolled back from {w:.0%}: caught on the canary",
    "ev_false": "v{v} rolled back from {w:.0%}, but it was a good build: a false alarm",
    "ev_cancel": "v{v} still on {w:.0%} when the window closed: cancelled",
    "ev_manual": "someone on call rolls v{v} back by hand",
    "never": "never",
    # the panel
    "tile_hurt": "Hurt",
    "tile_errors": "Errors",
    "toplist": "Router",
    "toplist_sub": "requests/s, last 1 s",
    "bar_live": "v{v} live",
    "bar_new": "v{v} new",
    "bar_none": "new –",
    "bar_hurt": "hurt",
    "head_bad_live": "v{v} is bad and live everywhere",
    "head_canary": "v{v} on {w:.0%}: measuring",
    "head_compare": "errors {be:.1%}→{ce:.1%} · slow {bs:.1%}→{cs:.1%}",
    "head_rolled_back": "v{v} rolled back; back to v{live}",
    "head_errors": "{e:.1%} errors: a dependency flakes",
    "head_live": "v{v} on 100%; no release running",
    # errors in your code
    "bad_weight": "decide() returned {value}: it must be a float from 0.0 to 1.0, the new build's share",
}

LESSON = Lesson(
    title="Canary releases",
    one_liner="Give a new build to a few users first, compare it with the old build over the same seconds, and "
              "widen it in steps only while it is not worse.",
    learn=(
        "Most incidents start with a change: a deploy, a config push, a flag. Tests catch a lot, but not what "
        "only production shows: real data, real traffic, real dependencies. Shipping a build to every user at "
        "once turns every bad build into an outage for everyone.",
        "A canary release sends a small share of the traffic (1-5%) to the new build and watches it. A crash "
        "loop shows in seconds, on a few users, and the release rolls back on its own. That is already a big "
        "step: the blast radius is the canary's share.",
        "Fixed rules are a weak judge. A latency regression has no errors, so an error limit lets it through. "
        "A fixed number cannot tell a bad build from a bad moment: when a database fails over, both builds "
        "fail more, and the rule blames the new one. Set it low and noise rolls back good builds; set it high "
        "and subtle regressions slip under it.",
        "Compare the canary with a baseline: the old build, serving the rest of the traffic over the same "
        "seconds. A two-proportion z-test tells whether the canary's error (or slow) share is really higher "
        "than the baseline's or just noise. Wait for enough samples (a minimum count) before you decide, "
        "and keep the bar strict: you test many metrics, many times.",
        "Measure each step on its own, in total and per endpoint or segment: a bug that breaks 5% of the "
        "traffic is diluted in the total. Ramp in steps (5% → 25% → 50% → 100%), each baked long enough, and "
        "roll back automatically: bad builds never reach everyone, good ones still ship in about a minute.",
    ),
    watch_for=(
        "Everywhere at once: the first build is slow for everyone; dots turn orange and p99 jumps for two minutes.",
        "Fixed canary: a purple trickle goes to one instance; the crash loop is undone in seconds, but the slow build goes live, and a flaky dependency rolls back a good one.",
        "Staged canary: the purple share climbs 5% → 25% → 50% → 100% for good builds; bad ones are undone on the first steps.",
    ),
    build=(
        ("Argo Rollouts: a staged canary with analysis",
         "strategy:\n"
         "  canary:\n"
         "    analysis:\n"
         "      templates: [{templateName: error-rate-vs-baseline}]\n"
         "    steps:\n"
         "    - setWeight: 5\n"
         "    - pause: {duration: 5m}\n"
         "    - setWeight: 25\n"
         "    - pause: {duration: 10m}\n"
         "    - setWeight: 50\n"
         "    - pause: {duration: 10m}"),
        ("PromQL: the canary's error ratio over the baseline's",
         "  sum(rate(http_requests_total{track=\"canary\",code=~\"5..\"}[5m]))\n"
         "/ sum(rate(http_requests_total{track=\"canary\"}[5m]))\n"
         "/ ( sum(rate(http_requests_total{track=\"baseline\",code=~\"5..\"}[5m]))\n"
         "  / sum(rate(http_requests_total{track=\"baseline\"}[5m])) )"),
        ("Python: the judge in this lab",
         "def worse(canary, baseline):\n"
         "    for c, b in ((canary.errors, baseline.errors), (canary.slow, baseline.slow)):\n"
         "        if c >= MIN_BAD and z_score(c, canary.requests, b, baseline.requests) > Z_LIMIT:\n"
         "            return True\n"
         "    return False"),
    ),
    checklist=(
        "Never ship to everyone at once: start with a small canary (1-5%) and an automatic rollback.",
        "Compare the canary with a baseline running the old build at the same time, not with a fixed number.",
        "Judge errors AND latency (and saturation): a slow build is a bad build.",
        "Wait for a minimum number of requests before deciding; use a strict bar when you test many metrics often.",
        "Look per endpoint or customer segment too: a bug in a small one is diluted in the total.",
        "Ramp in steps with a bake time each; bound the total time, so good builds still ship quickly.",
    ),
    refs=(
        Ref("Google SRE Workbook: Canarying Releases",
            "https://sre.google/workbook/canarying-releases/",
            "Canary vs control, picking metrics, and why the population size and duration matter."),
        Ref("Introducing Kayenta: automated canary analysis (Google and Netflix)",
            "https://cloud.google.com/blog/products/gcp/introducing-kayenta-an-open-automated-canary-analysis-tool-from-google-and-netflix",
            "A baseline cluster next to the canary, and a statistical judge."),
        Ref("Spinnaker: How canary judgment works",
            "https://spinnaker.io/docs/guides/user/canary/judge/",
            "Comparing canary and baseline metric by metric, then scoring."),
        Ref("Argo Rollouts: Canary deployment strategy",
            "https://argo-rollouts.readthedocs.io/en/stable/features/canary/",
            "setWeight and pause steps, with analysis and automatic abort."),
        Ref("Martin Fowler: CanaryRelease",
            "https://martinfowler.com/bliki/CanaryRelease.html",
            "The idea, in one page."),
        Ref("Wikipedia: Two-proportion Z-test",
            "https://en.wikipedia.org/wiki/Two-proportion_Z-test",
            "The test behind z_score, with its assumptions."),
    ),
    try_next=(
        "Do stage 1 in labs/canary_releases/main.py and watch the crash loop undone in seconds, and the slow build go live.",
        "Do stage 2 and watch good builds climb 5% → 25% → 50% → 100% while bad ones are undone on the canary.",
        "Set Z_LIMIT to 3 and count the good builds rolled back; drop the per-endpoint check and watch the /pay bug.",
    ),
)

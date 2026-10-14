"""Lab retry_storm, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Retry storm"
SUMMARY = "The service goes down at random. Retry the failed calls without piling on load."
PARAMS = {"rate": "user requests per second"}

INCIDENT = IncidentText("Outage", "the outage", "the next outage")
VERBS = {"down": "DOWN", "up": "UP"}
CAUSES = {
    "bad_deploy": "bad deploy, every call gets a 503",
    "node_crashed": "the node crashed, connections refused",
    "expired_cert": "an expired TLS certificate, every handshake fails",
    "config_push": "a config push broke routing",
    "pool_exhausted": "its database connection pool is exhausted",
    "replica_died": "a database replica died",
    "out_of_memory": "one of three nodes is out of memory",
    "noisy_neighbour": "a noisy neighbour is starving the CPU",
    "slow_dependency": "a slow dependency is timing out",
    "bad_canary": "a canary deploy with a bug",
}

STAGES = [
    StageText("No retry",
              "Challenge: the service goes down at random, and users fail. Retry the failed calls.",
              "Stage 1: retry failed calls in Client"),
    StageText("Retry",
              "Challenge: retries come straight back and hammer the service. Wait longer each time.",
              "Stage 2: sleep backoff_delay(attempt) between retries (exponential)"),
    StageText("Retry + backoff",
              "Challenge: every user backs off by the same amount, so retries come in waves. Add jitter.",
              "Stage 3: add full jitter to backoff_delay"),
    StageText("Retry + backoff + jitter",
              "Challenge: jitter spreads the retries, but they still pile 4x the load on. Cap them.",
              "Stage 4: spend a RetryBudget on every retry"),
    StageText("Retry + backoff + jitter + budget",
              "Solved: retries back off with jitter and spend a budget, so the load stays flat.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "Client must return results"),
    "retries": GoalText("Retries ≥ 3%", "retry ServiceError in Client"),
    "backoff": GoalText("Backoff ≥ 1.5x", "sleep backoff_delay(attempt)"),
    "jitter": GoalText("Jitter ≥ 25%", "add jitter to backoff_delay"),
    "load": GoalText("Load < 1.5x", "spend a RetryBudget token"),
    "served": GoalText("Served ≥ 90%", "retry once it is back"),
}

LEGEND = {"idle": "idle", "first_try": "first try", "retries": "retry 1,2,3", "failed": "failed",
          "served": "served", "limit": "limit", "incident": "incident"}

STRINGS = {
    # the cluster picture: clients -> your Client -> the service
    "pic_state": "client → service: {state}",
    # incidents
    "partial_outage": "Partial outage",
    "down": "is down: {cause}",
    "back_up": "is back up",
    "failing": "is failing {share:.0%} of calls: {cause}",
    "healthy_again": "is healthy again",
    "warn_load": "load {load:.1f}x what users ask",
    # goal values
    "avg": "avg {value:.1f}x",
    "few": "few",
    # the panel
    "tile_load": "Load",
    "tile_retries": "Retries",
    "tile_served": "Served",
    "bar_ask": "Users ask",
    "bar_get": "We get",
    "limit": "limit {limit:.0f}/s",
    "head_down": "Down: we get {load:.1f}x what users ask",
    "head_failing": "Failing {share:.0%}: we get {load:.1f}x what users ask",
    "head_recovered": "Recovered {seconds:.0f} s after the outage",
    "head_draining": "Back up; retries still draining",
    "head_load": "Load: {load:.1f}x what users ask",
    "note_dots": "Dots are a sample of calls, slowed down (cosmetic).",
    # errors in your code
    "stuck": "a request has been running for over {seconds:.0f} s: does Client.call retry forever?",
}

LESSON = Lesson(
    title="Retry storm",
    one_liner="The service goes down for a few seconds. Callers that retry at once turn 100 calls/s into ~400.",
    learn=(
        "When a service fails, every caller sees errors and tries again straight away. With 3 quick "
        "retries, one user request becomes up to 4 calls, so the service gets ~4x its normal traffic "
        "at the moment it is weakest. Across layers it multiplies: 3 retries in each of 3 layers can "
        "mean 64 attempts at the bottom.",
        "Backoff with jitter: wait longer after each failure, and pick the wait at random so clients do "
        "not retry in lockstep. Full jitter sleeps uniform(0, min(cap, base * 2**attempt)).",
        "A retry budget: backoff spreads retries out but does not cap them. A budget does. Every request "
        "adds a fraction of a token (say 0.1), every retry spends one, and when the bucket is empty you "
        "fail fast. Retry traffic stays near 10% extra, however long the outage.",
        "Pick one layer to retry (client library, mesh or gateway) and make the others fail fast.",
    ),
    watch_for=(
        "No retry: during the outage the Served tile drops to 0% and users fail (red).",
        "Retry: orange dots are retries, straight back at the service. 'We get' is ~4x 'Users ask'.",
        "Retry + backoff: the waits double each round, but every user waits the same: waves.",
        "Retry + backoff + jitter: the retries spread out, but the load is still ~4x.",
        "Retry + backoff + jitter + budget: a few retries get through, then the budget runs dry.",
        "The budget does not bring the service back faster; it stops you burying it while it is down.",
    ),
    build=(
        ("In Python (stamina wraps tenacity with safe defaults)",
         "import httpx, stamina\n\n"
         "@stamina.retry(on=httpx.TransportError, attempts=3)\n"
         "async def call_b(client: httpx.AsyncClient) -> dict:\n"
         "    r = await client.get(\"http://b/work\", timeout=1.0)   # per-try timeout\n"
         "    r.raise_for_status()\n"
         "    return r.json()"),
        ("gRPC service config: retry throttling is this lab's budget",
         "\"retryThrottling\": {\"maxTokens\": 10, \"tokenRatio\": 0.1}"),
        ("Envoy cluster: a retry budget",
         "circuit_breakers:\n"
         "  thresholds:\n"
         "  - retry_budget:\n"
         "      budget_percent: {value: 10.0}\n"
         "      min_retry_concurrency: 3"),
    ),
    checklist=(
        "Exactly one layer retries. List them: SDK, client library, mesh, gateway.",
        "Retry only transient errors (connect failures, 503, 429) on requests that are safe to repeat.",
        "A timeout per try, and an overall deadline passed down to the next call.",
        "Exponential backoff with full jitter and a cap. Honour Retry-After.",
        "A retry budget or throttle, around 10%.",
        "Metrics: retries per first try, attempts per request, budget exhausted. Alert on the ratio.",
        "Test it: stop a dependency in staging and watch calls/s. It should look like the last stage.",
    ),
    refs=(
        Ref("AWS Builders' Library: Timeouts, retries and backoff with jitter",
            "https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/",
            "When to retry, when not to, and why jitter matters."),
        Ref("AWS Architecture Blog: Exponential Backoff And Jitter",
            "https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/",
            "Simulations of full, equal and decorrelated jitter; the formula used here."),
        Ref("Google SRE book: Addressing Cascading Failures",
            "https://sre.google/sre-book/addressing-cascading-failures/",
            "Randomised backoff, retry limits, and how layered retries multiply."),
        Ref("gRPC: Retry",
            "https://grpc.io/docs/guides/retry/",
            "Retry policy and retry throttling (maxTokens, tokenRatio)."),
        Ref("Envoy: circuit breakers and retry budgets",
            "https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/circuit_breaking",
            "Envoy's retry budget caps retries as a share of active requests."),
    ),
    try_next=(
        "Do stage 1 in labs/retry_storm/main.py, save, and watch the load climb.",
        "Do stage 2 and watch the Backoff goal turn green, while the load stays high.",
        "Do stage 3 and watch the Jitter goal turn green.",
        "Do stage 4 and watch the orange disappear while the service is down.",
        "Run `uv run pytest labs/retry_storm` and watch the x's turn into X's.",
    ),
)

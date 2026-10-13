from core.lessons import Lesson, Ref

LESSON = Lesson(
    title="Retry storm",
    one_liner="Our service goes down for a few seconds. Callers that retry at once turn 100 calls/s into ~400.",
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

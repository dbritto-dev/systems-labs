"""Lab webhook_delivery, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Webhook delivery"
SUMMARY = "Send every event to 20 customer endpoints, in order, while some are down or slow."
PARAMS = {"rate": "events made per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"down": "DOWN", "hang": "HANG", "slow": "SLOW", "poison": "POISON", "burst": "BURST", "back": "BACK",
         "calm": "CALM"}
CAUSES = {
    "deploy": "their deploy answers 503 until it finishes",
    "cert_expired": "their TLS certificate expired: every handshake fails",
    "maintenance": "they are in maintenance mode and answer 503",
    "crashloop": "their webhook service is crash-looping: connections are refused",
    "dns": "a DNS change points their hostname at an old IP: connections hang",
    "firewall": "a new firewall rule drops our packets without a word",
    "allowlist": "they forgot our new IPs in their allowlist: packets are dropped",
    "no_backends": "their load balancer accepts connections, but no server is behind it",
    "database": "their database is struggling: each webhook takes seconds",
    "sync_calls": "they call a slow API before answering each webhook",
    "table_lock": "a long migration locks their orders table",
    "swapping": "their only server is out of memory and swapping",
    "emoji": "an emoji in a customer's name crashes their parser",
    "null_field": "a null discount code makes their handler throw",
    "currency": "orders in a new currency break their code",
    "big_payload": "orders with hundreds of items exceed their body size limit (413)",
    "flash_sale": "a flash sale",
    "black_friday": "Black Friday starts",
    "bulk_import": "a merchant bulk-imports orders",
    "newsletter": "a newsletter sends everyone to the shop at once",
}

STAGES = [
    StageText("Fire once",
              "Challenge: a down endpoint loses its events; a hanging one holds every worker. Retry.",
              "Stage 1: timeout each POST; retry failures with backoff + jitter"),
    StageText("Retries",
              "Challenge: one dead endpoint still eats the workers, and events arrive out of order.",
              "Stage 2: a queue per endpoint, in order per key; park it after failures"),
    StageText("Queue per endpoint",
              "Solved: nothing lost, every order in order, and a dead endpoint costs the others nothing.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "deliver in next()"),
    "lost": GoalText("Lost = 0", "retry with backoff"),
    "order": GoalText("Out of order = 0", "one event per order at once"),
    "p99": GoalText("Healthy p99 < 1s", "a queue + cap per endpoint"),
    "waste": GoalText("Wasted work ≤ 10%", "park a failing endpoint"),
}

LEGEND = {"idle": "idle", "first": "1st attempt", "retry": "retry", "delivered": "delivered",
          "out_of_order": "out of order", "failed": "failed", "gave_up": "given up", "limit": "events made",
          "incident": "incident"}

STRINGS = {
    # incidents
    "down_start": "endpoint #{n} is down: {cause}",
    "down_end": "endpoint #{n} answers again",
    "hang_start": "endpoint #{n} never answers: {cause}",
    "hang_end": "endpoint #{n} answers again",
    "slow_start": "endpoint #{n} takes 2.5-8 s to answer: {cause}",
    "slow_end": "endpoint #{n} is fast again",
    "poison_start": "endpoint #{n} fails forever on 1 in 20 new events: {cause}",
    "poison_end": "new events are fine again; the bad ones still fail",
    "burst_start": "{times:.1f}x the events: {cause}",
    "burst_end": "the burst is over",
    "warn_lost": "{n} events given up",
    "warn_stuck": "{n} of {of} workers stuck on one endpoint",
    # the panel
    "tile_lost": "Lost",
    "tile_order": "Order",
    "tile_p99": "p99",
    "bar_made": "Made",
    "bar_sent": "Sent",
    "bar_ended": "Ended",
    "limit": "made",
    "head_lost": "{n} events given up in 10 s",
    "head_stuck": "{n} of {of} workers stuck on #{endpoint}",
    "head_order": "{n} events delivered out of order in 10 s",
    "head_down": "Endpoint #{n} is down",
    "head_hang": "Endpoint #{n} never answers",
    "head_slow": "Endpoint #{n} is slow",
    "head_poison": "Endpoint #{n} rejects malformed events",
    "head_burst": "A burst of events",
    "head_ok": "Every event delivered, in order",
    "stat_delivered": "delivered",
    "stat_lost": "lost",
    "stat_pending": "pending",
    "stat_order": "out of order",
    "stat_busy": "workers",
    "title": "Webhooks",
    "subtitle": "per second, last 1 s",
    # the pictures
    "state_down": "#{n} DOWN",
    "state_hang": "#{n} HANGS",
    "state_slow": "#{n} SLOW",
    "state_poison": "#{n} POISON",
    "state_burst": "BURST",
    "pic_state": "{state} · workers {busy}/{of}",
    "note": "Endpoints: red dead, orange slow. Dots are a sample (cosmetic).",
}

LESSON = Lesson(
    title="Webhook delivery",
    one_liner="Deliver every event to every customer, in order, without letting one broken endpoint "
              "take the others down.",
    learn=(
        "A webhook is an HTTP POST you send to a customer's server when something happens (order.created, "
        "order.paid). You do not control that server: it gets deployed, its certificate expires, its DNS "
        "changes, its database struggles. So delivery is at-least-once: store the event, POST it, and keep "
        "it until you get a 2xx. Fire-and-forget loses every event sent while the endpoint is down.",
        "Retry with exponential backoff and jitter, and put a timeout on every attempt. Without a timeout, "
        "an endpoint whose connections hang holds each worker for the HTTP client's default (30 s here, "
        "minutes in some clients), and a shared pool of workers is soon all stuck on one customer.",
        "Retries alone are not enough. A shared queue lets a dead or slow endpoint eat the workers with "
        "its timeouts and retries, so every other customer waits (no isolation). And retries reorder: "
        "order.paid succeeds while order.created waits for its next retry. Give each endpoint its own "
        "queue and a cap on its share of the workers (a bulkhead), send one event per resource key at a "
        "time, oldest first, and after N failures in a row park the endpoint: probe it now and then, and "
        "replay its backlog, in order, once it answers again. An event that fails on its own while the "
        "endpoint works (a malformed one) is given up after a few attempts, so it cannot block its key forever.",
        "Sign every webhook: an HMAC-SHA256 of the timestamp and the body with a secret per endpoint, in a "
        "header, so the customer can check it came from you and was not replayed (reject old timestamps). "
        "And send an event id: at-least-once means a timed-out POST may have been processed, and the "
        "customer must ignore the duplicate.",
    ),
    watch_for=(
        "Fire once: when endpoint #1 hangs, every worker ends up waiting on it (orange dots by the red "
        "node), the other endpoints starve, and its events are lost (purple).",
        "Retries: nothing is lost, but #1's timeouts and retries still fill the workers, and once it is "
        "back, events of the same order arrive out of order (deep orange).",
        "Queue per endpoint: at most 4 workers wait on #1, then it is parked with one probe every 5 s; "
        "the other endpoints never notice, and the backlog is replayed in order.",
    ),
    build=(
        ("Sign each webhook (the Standard Webhooks scheme)",
         "msg = f\"{event_id}.{timestamp}.{body}\"\n"
         "sig = base64.b64encode(hmac.new(secret, msg.encode(), hashlib.sha256).digest())\n"
         "headers = {\"webhook-id\": event_id, \"webhook-timestamp\": str(timestamp),\n"
         "           \"webhook-signature\": f\"v1,{sig.decode()}\"}"),
        ("Verify it on the receiving side, in constant time",
         "expected = hmac.new(secret, msg.encode(), hashlib.sha256).digest()\n"
         "if abs(time.time() - timestamp) > 300 or not hmac.compare_digest(expected, received):\n"
         "    return 400  # forged or replayed"),
        ("A timeout and a capped, jittered backoff with httpx",
         "client = httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=1.0))\n"
         "delay = random.uniform(0, min(30, 0.5 * 2 ** (attempt - 1)))  # full jitter"),
    ),
    checklist=(
        "Store the event before you send it; delete it only after a 2xx.",
        "Put a timeout on every attempt: connect and read, a few seconds at most.",
        "Retry with exponential backoff and full jitter, capped, for hours or days.",
        "One queue per endpoint, with a cap on how many workers it may hold at once.",
        "Deliver per resource key in order: one in flight per key, oldest first; or send a sequence number "
        "and let the customer fetch the latest state.",
        "After N failures in a row, disable (park) the endpoint, tell the customer, probe it, and replay "
        "its backlog when it is healthy.",
        "Sign every webhook with an HMAC of the timestamp and body, and send a unique event id for dedup.",
        "Expect customers to answer 2xx fast and do the work later; alarm on each endpoint's backlog age.",
    ),
    refs=(
        Ref("Standard Webhooks: the specification",
            "https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md",
            "Event ids, timestamps, HMAC signatures, retries: a common scheme for webhook senders."),
        Ref("Stripe: Receive events in your webhook endpoint",
            "https://docs.stripe.com/webhooks",
            "Retries for days, disabled endpoints, signatures, and why order is not guaranteed."),
        Ref("GitHub: Validating webhook deliveries",
            "https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries",
            "Checking an HMAC-SHA256 signature in constant time."),
        Ref("AWS Builders' Library: Timeouts, retries, and backoff with jitter",
            "https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/",
            "Why every call needs a timeout, and retries need backoff, jitter and a limit."),
        Ref("AWS Architecture Blog: Exponential Backoff And Jitter",
            "https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/",
            "Full jitter, equal jitter and decorrelated jitter, compared."),
        Ref("AWS Builders' Library: Workload isolation using shuffle-sharding",
            "https://aws.amazon.com/builders-library/workload-isolation-using-shuffle-sharding/",
            "Why one noisy customer must not share every worker with all the others."),
    ),
    try_next=(
        "Do stage 1 in labs/webhook_delivery/main.py and watch #1 hang again: nothing is lost, but the "
        "workers still pile up by it.",
        "Do stage 2 and watch the same incident: four workers wait on #1, then it is parked and probed.",
        "Set DISABLE_AFTER to 1000 (never park) and watch a hang: #1 keeps its 4 workers waiting the "
        "whole time, and the wasted work goes over 10%.",
    ),
)

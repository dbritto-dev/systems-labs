"""Lab load_balancing, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Load balancing"
SUMMARY = "One of 8 servers turns slow but keeps its share. Steer by load, then by two random choices."
PARAMS = {"rate": "user requests per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"slow": "SLOW", "fast": "FAST", "cold": "COLD", "warm": "WARM"}
CAUSES = {
    "noisy_neighbour": "a noisy neighbour hogs its host's CPU",
    "gc_storm": "a GC storm: the heap is nearly full",
    "bad_disk": "its disk is failing and every read retries",
    "degraded_az": "its availability zone's network is degraded",
    "autoscaler": "the autoscaler replaced it: empty caches, a cold JIT",
    "spot_reclaimed": "its spot instance was reclaimed; the new one boots cold",
    "deploy_restart": "a rolling deploy restarted it with cold caches",
}

STAGES = [
    StageText("Round robin",
              "Challenge: a slow server still gets 1 request in 8; its queue grows, requests time out.",
              "Stage 1: send each request to the server with the fewest in flight"),
    StageText("Least outstanding",
              "Challenge: with stale load reports, every balancer herds onto the server that looks idle.",
              "Stage 2: pick two servers at random, send to the less loaded"),
    StageText("Power of two choices",
              "Solved: the slow server is avoided and requests spread out, even with stale reports.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "pick() must return a server"),
    "share": GoalText("Slow server ≤ 10%", "send to the least loaded"),
    "p99": GoalText("p99 < 750ms", "pick 2 at random, less load"),
    "served": GoalText("Served ≥ 99%", "stop herding: two choices"),
    "recovered": GoalText("Recovered ≥ 95%", "spread the load again"),
}

LEGEND = {"idle": "idle", "request": "request", "waits": "waits / queue", "served": "served",
          "timed_out": "timed out", "server": "server", "slow_server": "slow server", "fair": "fair share",
          "incident": "incident"}

STRINGS = {
    "note_dots": "Dots are a sample, slowed down (cosmetic).",
    # the pictures
    "topology": "4 balancers → 8 servers",
    "lanes_balancers": "4 balancers",
    "state_sick": "{state} s{server}",
    # incidents
    "slow_server": "Slow server",
    "cold_server": "Cold server",
    "is_slow": "s{server} is {times:.0f}x slower: {cause}",
    "fast_again": "s{server} is fast again",
    "is_cold": "s{server} replaced, {times:.0f}x slower at first: {cause}",
    "warm_again": "s{server} has warmed up",
    "warn_timeouts": "{n:.0f} timeouts in one second (504)",
    # the panel
    "tile_share": "On slow",
    "tile_served": "Served",
    "toplist": "Servers",
    "bar_busiest": "Most s{n}",
    "bar_quietest": "Least s{n}",
    "bar_slow": "Slow s{n}",
    "bar_no_slow": "Slow –",
    "limit_fair": "fair {n}/s",
    "head_timeouts": "{n} requests timed out (504)",
    "head_herding": "Herding: {share:.0%} to one server",
    "head_full_share": "s{n} is slow and still gets {share:.0%}",
    "head_avoided": "s{n} is slow; balancers avoid it",
    "head_spread": "Requests spread over {n} servers",
    "note_chart": "The chart: requests/s to the slow server, and timeouts.",
    # errors in your code
    "bad_pick": "pick() returned {value}: it must be a server index, 0 to {last}",
}

LESSON = Lesson(
    title="Load balancing",
    one_liner="A balancer that ignores load keeps feeding a slow server. Steering to the least loaded herds on stale data; two random choices do not.",
    learn=(
        "A load balancer spreads requests over a pool of servers. Round robin gives each server the same "
        "number of requests, which is fair only while every server is equally fast.",
        "Servers are not equally fast for long: a noisy neighbour on the same host, a garbage collection "
        "storm, a failing disk, a degraded availability zone, or a fresh replacement with cold caches. "
        "Round robin still sends the slow one 1 request in 8: its queue grows until requests time out, "
        "and the whole fleet's p99 is that one server's.",
        "Least outstanding requests sends each request to the server with the fewest in flight, so a slow "
        "server, which keeps a queue, gets fewer. But a balancer only knows the load as of its last report, "
        "and there are several balancers. Until the next report, every request goes to the same 'idle' "
        "server: a herd. When that server is the slow one, or a cold one that just joined, the herd times out.",
        "The power of two choices picks two servers at random and sends the request to the less loaded of "
        "the two. The busiest server is never chosen, and the rest share the traffic instead of one server "
        "taking it all. Mitzenmacher showed it does almost as well as the least loaded with fresh data, and "
        "much better with old data.",
        "Real balancers add slow start (ramp a new server up over a few seconds), outlier detection (eject a "
        "server that keeps failing) and timeouts with retries on another server.",
    ),
    watch_for=(
        "Round robin: the slow server (purple) gets its full fair share; its queue grows and users time out in red.",
        "Least outstanding: the slow server gets less, but every half second whole bursts land on one server.",
        "Power of two choices: traffic spreads over the healthy servers and the slow one gets a trickle.",
    ),
    build=(
        ("Envoy: least request with two choices (its default)",
         "clusters:\n"
         "- name: backend\n"
         "  lb_policy: LEAST_REQUEST\n"
         "  least_request_lb_config:\n"
         "    choice_count: 2"),
        ("NGINX: random two, the less loaded by connections",
         "upstream backend {\n"
         "    random two least_conn;\n"
         "    server 10.0.0.1;\n"
         "    server 10.0.0.2;\n"
         "}"),
        ("HAProxy: power of two random choices",
         "backend app\n"
         "    balance random(2)\n"
         "    server s1 10.0.0.1:8080 check slowstart 30s"),
    ),
    checklist=(
        "Balance on load (outstanding requests), not only on turns: round robin feeds a slow server forever.",
        "Several balancers, or load data that arrives late? Use two random choices, not the global minimum.",
        "Ramp new servers up slowly (slow start), so a cold one is not handed a full share at once.",
        "Set a timeout per request and eject outliers (servers that keep failing or are much slower).",
        "Metrics: requests and p99 per server, outstanding per server, timeouts (504s) per server.",
    ),
    refs=(
        Ref("Mitzenmacher: The Power of Two Choices in Randomized Load Balancing",
            "https://www.eecs.harvard.edu/~michaelm/postscripts/mythesis.pdf",
            "The thesis: two random choices beat one by an exponential factor."),
        Ref("Mitzenmacher: How Useful Is Old Information?",
            "https://www.eecs.harvard.edu/~michaelm/postscripts/tpds2000.pdf",
            "Why the least loaded server herds on stale data, and two choices do not."),
        Ref("Envoy: supported load balancers",
            "https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/load_balancers",
            "Round robin, least request with two choices, and slow start."),
        Ref("Marc Brooker: The power of two random choices",
            "https://brooker.co.za/blog/2012/01/17/two-random.html",
            "A simulation of best of two against the least loaded with stale data."),
        Ref("HAProxy: Test driving power of two random choices",
            "https://www.haproxy.com/blog/power-of-two-load-balancing",
            "Measured on many balancers sharing a pool of servers."),
    ),
    try_next=(
        "Do stage 1 in labs/load_balancing/main.py and watch the slow server's share drop, then the bursts.",
        "Do stage 2 and watch the bursts disappear and the timeouts stop.",
        "Try picking three at random instead of two: does it get better, or start to herd again?",
    ),
)

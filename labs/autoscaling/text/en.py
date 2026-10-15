"""Lab autoscaling, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Autoscaling"
SUMMARY = "A fleet that must follow the traffic. Scale on CPU one at a time, then track requests per instance."
PARAMS = {"rate": "user requests per second on an average day (the day swings ±40%)"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"surge": "SURGE", "eases": "EASES", "drop": "DROP", "back": "BACK", "noisy": "NOISY",
         "quiet": "QUIET", "cold": "COLD", "warm": "WARM"}
CAUSES = {
    "tv_ad": "a TV ad airs and viewers open the app",
    "marketing_push": "a marketing email goes out to every user",
    "viral_post": "a post about us goes viral",
    "flash_sale": "a flash sale starts",
    "region_failover": "traffic fails over to another region",
    "upstream_outage": "an upstream outage: the gateway in front of us drops requests",
    "client_bug": "a mobile release stops calling us",
    "batch_job": "a batch job runs on the same hosts",
    "backup": "a backup compresses files on the same hosts",
    "log_shipper": "a log shipper falls behind and burns CPU",
    "deploy": "a rolling deploy restarts the instances, batch by batch",
    "config_push": "a config push restarts the instances, batch by batch",
    "node_rotation": "a security patch rotates the hosts, batch by batch",
}

STAGES = [
    StageText("Fixed fleet",
              "Challenge: a fixed fleet never grows: the surge overloads it, and at night it sits idle.",
              "Stage 1: +1 instance above 70% CPU, -1 below 30%"),
    StageText("CPU thresholds",
              "Challenge: one instance per tick falls behind a surge, and CPU is a misleading signal.",
              "Stage 2: track requests/s per instance; scale in slowly"),
    StageText("Target tracking",
              "Solved: the fleet follows the traffic in proportional steps, with headroom, no flapping.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "desired() must return an int"),
    "served": GoalText("Served ≥ 99%", "scale in proportional steps"),
    "p99": GoalText("p99 < 1s", "fit the fleet to the traffic"),
    "headroom": GoalText("Headroom ≥ 50%", "target 10 req/s per instance"),
    "flaps": GoalText("Flaps ≤ 2", "scale in slowly: stabilise"),
    "cost": GoalText("Cost ≤ ideal +50%", "track requests, not CPU"),
}

LEGEND = {"idle": "idle", "request": "request", "waits": "waits / queue", "served": "served",
          "failed": "timed out", "warm": "warm instance", "warming": "warming up", "booting": "booting",
          "short": "missing", "max": "max fleet", "incident": "incident"}

STRINGS = {
    "note_dots": "Dots are a sample, slowed down (cosmetic).",
    "note_chart": "The chart: the fleet each second, and in red the instances it lacks at the target.",
    # the pictures
    "fleet_state": "{state} {n}+{booting}",
    "cluster_state": "{state}  {n} up · {booting} booting · needs {need}",
    # the relay picture: the load on the instances, the fleet serving / needed
    "relay_load": "load {load:.0%}",
    "relay_fleet": "serving {n}/{need}",
    # incidents
    "surge": "Traffic surge",
    "drop": "Traffic drop",
    "noisy": "Noisy CPU",
    "cold": "Cold-start wave",
    "surge_start": "traffic climbs to {times:.1f}x: {cause}",
    "surge_end": "the surge eases off",
    "drop_start": "traffic falls to {share:.0%}: {cause}",
    "drop_end": "traffic comes back, slowly",
    "noisy_start": "CPU reads up to +{cpu:.0%} on every host: {cause}",
    "noisy_end": "the CPU noise is gone",
    "cold_start": "{share:.0%} of the instances at a time restart cold: {cause}",
    "cold_end": "every instance is warm again",
    "warn_timeouts": "{n:.0f} requests timed out in one second (504)",
    "warn_flap": "flapping: {n} instances added and removed within 30 s",
    # the panel
    "tile_headroom": "Spare",
    "tile_cost": "Cost",
    "toplist": "Fleet",
    "toplist_sub": "instances now",
    "bar_fleet": "Fleet",
    "bar_needed": "Needed",
    "bar_actions": "Act/10m",
    "limit_max": "max {n}",
    "head_timeouts": "{n} requests timed out: the fleet is too small",
    "head_flapping": "Flapping: {n} instances added and removed in 30 s",
    "head_booting": "{n} booting: the surge outruns the fleet",
    "head_short": "Needs {need}, has {n}: scale out",
    "head_waste": "Needs {need}, pays for {n}: scale in",
    "head_noisy": "CPU reads {cpu:.0%}; the traffic did not change",
    "head_fits": "{n} instances for {need} needed: on target",
    # errors in your code
    "bad_desired": "desired() returned {value}: it must be an int, the number of instances you want",
}

LESSON = Lesson(
    title="Autoscaling",
    one_liner="Grow and shrink the fleet with the traffic: proportional steps on a load signal, headroom for "
              "the boot time, and slow scale-in so it does not flap.",
    learn=(
        "Traffic is never flat: it follows the day, comes in bursts, and jumps when a TV ad airs or a post "
        "goes viral. A fixed fleet is sized for one moment: it is overloaded at the peaks and paid for, idle, "
        "at night.",
        "An autoscaler looks at recent metrics every few seconds and sets the desired number of instances. "
        "A new instance is not capacity yet: it boots (20-40 s, paid for, serving nothing), then serves "
        "slowly while its caches and JIT warm up. Whatever you order now arrives half a minute later.",
        "Threshold rules (add one instance above 70% CPU, remove one below 30%) are slow: one instance per "
        "tick cannot follow traffic that doubles in a minute. And CPU lies: a batch job on the same host, "
        "a cold JIT, garbage collection all raise it without more traffic.",
        "Target tracking computes the fleet the load needs in one step: requests/s divided by the "
        "requests/s you want per instance. Keep the target well below the maximum: that headroom absorbs "
        "bursts and covers the boot time while new instances come up.",
        "Two more rules keep it calm. Count instances still booting or warming as part of the fleet, or "
        "every tick orders them again (overshoot). Scale out at once, but scale in only to the highest "
        "recommendation of the last minute or so (a stabilisation window), or every dip removes instances "
        "the next burst needs (flapping).",
    ),
    watch_for=(
        "Fixed fleet: the surge fills the queues and users time out in red; later, at night, most instances idle.",
        "CPU thresholds: one light-orange node per tick, always behind the surge; the noisy CPU incident adds instances for nothing.",
        "Target tracking: a batch of instances appears at once, boots, warms (orange to blue), and the fleet holds before it shrinks.",
    ),
    build=(
        ("AWS: target tracking on requests per target, with warm-up",
         "aws autoscaling put-scaling-policy --auto-scaling-group-name web \\\n"
         "  --policy-name requests-per-target --policy-type TargetTrackingScaling \\\n"
         "  --target-tracking-configuration '{\n"
         "    \"PredefinedMetricSpecification\": {\n"
         "      \"PredefinedMetricType\": \"ALBRequestCountPerTarget\",\n"
         "      \"ResourceLabel\": \"app/web/123/targetgroup/web/456\"},\n"
         "    \"TargetValue\": 600}'\n"
         "aws autoscaling update-auto-scaling-group --auto-scaling-group-name web \\\n"
         "  --default-instance-warmup 60"),
        ("Kubernetes: HPA with a scale-down stabilisation window",
         "apiVersion: autoscaling/v2\n"
         "kind: HorizontalPodAutoscaler\n"
         "spec:\n"
         "  minReplicas: 2\n"
         "  maxReplicas: 40\n"
         "  metrics:\n"
         "  - type: Pods\n"
         "    pods:\n"
         "      metric: {name: http_requests_per_second}\n"
         "      target: {type: AverageValue, averageValue: \"10\"}\n"
         "  behavior:\n"
         "    scaleUp: {stabilizationWindowSeconds: 0}\n"
         "    scaleDown: {stabilizationWindowSeconds: 300}"),
        ("Python: the policy in this lab",
         "def desired(self, m):\n"
         "    want = max(MIN_INSTANCES, math.ceil(m.rps / TARGET_RPS))\n"
         "    self.wants.append((m.t, want))  # scale in only to the highest of the last STABILISE s\n"
         "    while self.wants[0][0] <= m.t - STABILISE:\n"
         "        self.wants.popleft()\n"
         "    return max(w for _, w in self.wants)"),
    ),
    checklist=(
        "Scale on a load signal that follows the traffic (requests/s or requests in flight per instance), not CPU alone.",
        "Size in one proportional step: ceil(load / target per instance), not one instance at a time.",
        "Keep headroom: a target near 50-60% of what an instance can do covers bursts and the boot time.",
        "Count booting and warming instances in the fleet (warm-up), so the next tick does not order them again.",
        "Scale out fast, scale in slowly (a stabilisation window); set a minimum and a maximum fleet.",
        "Metrics: desired vs running vs in-service instances, scaling actions per hour, p99, cost per request.",
    ),
    refs=(
        Ref("AWS: Target tracking scaling policies",
            "https://docs.aws.amazon.com/autoscaling/ec2/userguide/as-scaling-target-tracking.html",
            "Pick a metric and a target value; the group computes the capacity."),
        Ref("AWS: Set the default instance warmup",
            "https://docs.aws.amazon.com/autoscaling/ec2/userguide/ec2-auto-scaling-default-instance-warmup.html",
            "Why instances still warming up must not drive more scaling."),
        Ref("Kubernetes: Horizontal Pod Autoscaling",
            "https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/",
            "The proportional formula, not-ready pods, and the stabilisation window against flapping."),
        Ref("Google SRE Workbook: Managing Load",
            "https://sre.google/workbook/managing-load/",
            "Autoscaling, headroom, and what to do while new capacity comes up."),
        Ref("Brendan Gregg: CPU Utilization is Wrong",
            "https://www.brendangregg.com/blog/2017-05-09/cpu-utilization-is-wrong.html",
            "Why CPU busy is a poor measure of how loaded a service is."),
    ),
    try_next=(
        "Do stage 1 in labs/autoscaling/main.py and watch the fleet chase the surge one instance at a time.",
        "Do stage 2 and watch whole batches boot at once, then the fleet hold before it shrinks.",
        "Set STABILISE to 0 and watch the flaps; set TARGET_RPS to 18 and watch the surge time out.",
    ),
)

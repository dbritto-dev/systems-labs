"""Lab graceful_shutdown, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Graceful shutdown"
SUMMARY = "Deploys send SIGTERM to 6 instances behind a load balancer. Drain, then leave the balancer first."
PARAMS = {"rate": "user requests per second"}

INCIDENT = IncidentText("Shutdown", "the shutdown", "the next shutdown")
VERBS = {"deploy": "DEPLOY", "drain": "DRAIN", "scale_in": "SCALE", "done": "DONE"}
CAUSES = {
    "release": "a new release rolls out",
    "config_change": "a config change restarts every instance",
    "base_image": "a patched base image (a CVE fix) rolls out",
    "rollback": "a rollback to the previous release",
    "kernel_patch": "its node is drained for a kernel patch",
    "node_upgrade": "its node is drained for a node pool upgrade",
    "spot_reclaim": "its spot node is reclaimed (2-minute notice) and drained",
    "traffic_dip": "traffic dipped and the autoscaler scales in",
    "night_schedule": "a scheduled scale-in for the night",
}

STAGES = [
    StageText("Exit at once",
              "Challenge: SIGTERM kills in-flight requests, and the balancer still sends new ones there.",
              "Stage 1: drain: stop accepting, finish in-flight work, then exit"),
    StageText("Drain",
              "Challenge: nothing is cut, but the balancer keeps sending until its checks fail: errors.",
              "Stage 2: fail readiness, wait for the balancer, then drain"),
    StageText("Readiness off first",
              "Solved: the balancer stops sending first, then in-flight work drains: no errors.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "on_sigterm() must not raise"),
    "errors": GoalText("Errors ≤ 0.1%", "fail readiness, then wait"),
    "cut": GoalText("Cut mid-flight = 0", "drain before you exit"),
    "capacity": GoalText("Serving ≥ 5 of 6", "keep serving until removed"),
    "exited": GoalText("Exit before kill", "drain with a deadline"),
}

LEGEND = {"idle": "idle", "request": "request", "waits": "waits", "served": "served", "failed": "failed",
          "serving": "serving", "starting": "starting", "draining": "draining", "terminated": "terminated",
          "limit": "one instance", "incident": "shutdown"}

STRINGS = {
    "note_dots": "Dots are a sample, slowed down (cosmetic).",
    # the pictures
    "topology": "3 balancer nodes → 6 instances",
    "state_ok": "SERVING {n}/{of}",
    "state_starting": "STARTING s{slot} · {n}/{of}",
    "state_leaving": "LEAVING s{slot} · {n}/{of}",
    "state_draining": "DRAINING s{slot} · {n}/{of}",
    "state_refusing": "REFUSING s{slot} · {n}/{of}",
    "state_cut": "CUT s{slot} · {n}/{of}",
    # incidents
    "deploy": "Deploy",
    "drain": "Node drain",
    "scale_in": "Scale-in",
    "deploy_start": "Rolling deploy of {n} instances, one by one: {cause}",
    "deploy_end": "the last old instance has its SIGTERM; the balancer has caught up",
    "drain_start": "s{slot} gets SIGTERM; a new one starts elsewhere: {cause}",
    "drain_end": "s{slot}: the balancer has caught up",
    "scale_start": "s{slot} gets SIGTERM, no replacement: {cause}",
    "scale_end": "the autoscaler adds s{slot} back in 5 s",
    "warn_failed": "{n:.0f} requests failed in one second: sent to s{slot}",
    "warn_killed": "s{slot} killed (SIGKILL) after 30 s: {cut} cut",
    "warn_cut": "s{slot} exited with {cut} in flight: cut",
    # the panel
    "tile_errors": "Errors",
    "tile_cut": "Cut",
    "tile_serving": "Serving",
    "toplist": "Requests",
    "bar_new": "To others",
    "bar_old": "To old",
    "bar_failed": "Failed",
    "limit_one": "one: {n}/s",
    "head_failed": "{n} refused at s{slot}: still routed",
    "head_failed_any": "{n} requests failed",
    "head_cut": "s{slot} exited: {n} cut mid-flight",
    "head_draining": "s{slot} drains: {n} still in flight",
    "head_waiting": "s{slot} waits on balancer: {n} in flight",
    "head_starting": "s{slot} starts; not in rotation yet",
    "head_steady": "All {n} instances serving",
    "note_chart": "The chart: requests/s to old instances, and failures.",
    # errors in your code
    "bad_timeout": "drained() needs a number of seconds (or None), not {value}",
}

LESSON = Lesson(
    title="Graceful shutdown",
    one_liner="A deploy is a shutdown. Leave the load balancer first, then drain what is in flight, then exit before the hard kill.",
    learn=(
        "Every deploy, scale-in, node drain and spot reclaim ends an instance the same way: the orchestrator "
        "sends it SIGTERM and, a grace period later (30 s in Kubernetes), SIGKILL. What happens in between is "
        "up to the app, and the default is to exit at once.",
        "Exiting at once cuts every request in flight (the user gets a 502 or a reset connection), every "
        "WebSocket and stream, and every kept-alive connection. And the load balancer does not know yet: it "
        "learns only when its health checks fail several times in a row, so for seconds it keeps sending new "
        "connections to an instance that is gone.",
        "Draining fixes the first half: stop accepting new connections, close idle kept-alive connections "
        "(and answer the rest with 'Connection: close', and ask streams to reconnect), wait for in-flight "
        "work to finish, then exit. Nothing is cut. But a closed listener refuses the connections the "
        "balancer still sends, so users still see errors until the balancer notices.",
        "The order is the fix: first fail the readiness check and keep serving, wait until every balancer "
        "node has taken the instance out of rotation (checks × interval, plus the time it takes to apply "
        "it), then drain. Kubernetes users often put this wait in a preStop hook ('sleep 10'). Put a "
        "deadline on the drain so the process exits before the grace period ends: the hard kill cuts "
        "everything.",
        "The wait also protects capacity. An orchestrator moves to the next instance as soon as the new one "
        "is ready, often before the balancer sends it traffic. An old instance that keeps serving while it "
        "waits covers that gap; one that exits at once leaves two instances missing.",
    ),
    watch_for=(
        "Exit at once: the instance turns red (the balancer still sends to it) and grey; requests die in red.",
        "Drain: nothing is cut, but the instance refuses new connections for seconds: red at the door.",
        "Readiness off first: the instance stays orange while it serves and drains, and goes grey quietly.",
    ),
    build=(
        ("Kubernetes: wait for the balancer in preStop, and a grace period that covers the drain",
         "spec:\n"
         "  terminationGracePeriodSeconds: 30\n"
         "  containers:\n"
         "  - name: app\n"
         "    lifecycle:\n"
         "      preStop:\n"
         "        exec: {command: [\"sleep\", \"10\"]}\n"
         "    readinessProbe:\n"
         "      httpGet: {path: /ready, port: 8080}\n"
         "      periodSeconds: 2\n"
         "      failureThreshold: 3"),
        ("Go: readiness off, wait, then Shutdown with a deadline",
         "<-sigterm\n"
         "ready.Store(false)                    // /ready answers 503\n"
         "time.Sleep(10 * time.Second)          // the balancer takes it out\n"
         "ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)\n"
         "defer cancel()\n"
         "srv.Shutdown(ctx) // stop listening, close idle conns, wait for the rest"),
        ("Node.js: readiness off (/ready answers 503), wait, close, a deadline",
         "process.on('SIGTERM', async () => {\n"
         "  ready = false;\n"
         "  await sleep(10_000);\n"
         "  server.close(() => process.exit(0));\n"
         "  server.closeIdleConnections();\n"
         "  setTimeout(() => process.exit(1), 15_000).unref();\n"
         "});"),
    ),
    checklist=(
        "Handle SIGTERM: never exit at once with requests in flight. Make sure the signal reaches your process (PID 1, exec form).",
        "Fail readiness first, and keep serving until the balancer has taken you out: wait checks × interval plus its delay.",
        "Then stop accepting, close idle kept-alive connections, send 'Connection: close', ask WebSockets and streams to reconnect.",
        "Drain with a deadline, and exit before the grace period ends: the hard kill (SIGKILL) cuts everything.",
        "Metrics: 5xx and resets per deploy, requests in flight at exit, shutdown time, instances serving during a rollout.",
    ),
    refs=(
        Ref("Kubernetes: Pod lifecycle, termination of Pods",
            "https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination",
            "SIGTERM, preStop, the grace period and SIGKILL, and endpoints removed in parallel."),
        Ref("Kubernetes: Container lifecycle hooks",
            "https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/",
            "The preStop hook runs before SIGTERM, within the grace period."),
        Ref("AWS: Health checks for Application Load Balancer target groups",
            "https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html",
            "Interval, unhealthy threshold, and how a target leaves rotation."),
        Ref("Go: http.Server.Shutdown",
            "https://pkg.go.dev/net/http#Server.Shutdown",
            "Closes listeners, then idle connections, then waits for active ones, until the context ends."),
        Ref("AWS Load Balancer Controller: Pod readiness gate",
            "https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/deploy/pod_readiness_gate/",
            "Why a rollout can outrun the load balancer, and how to make it wait."),
    ),
    try_next=(
        "Do stage 1 in labs/graceful_shutdown/main.py and watch the cuts stop while the errors stay.",
        "Do stage 2 and watch the instance stay orange and serve until the balancer lets it go.",
        "Try a wait of exactly checks × interval, without the balancer's own delay: how many errors come back?",
    ),
)

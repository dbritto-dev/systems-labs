"""Lab event_loop_blocking, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Event loop blocking"
SUMMARY = "One asyncio loop, and blocking calls inside it. Offload them to threads, then to bounded pools."
PARAMS = {"rate": "requests per second on a normal day"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"upload": "UPLOAD", "slow": "SLOW", "report": "REPORT", "gc": "GC", "done": "DONE", "fast": "FAST",
         "calm": "CALM"}
CAUSES = {
    "wedding_photos": "a photographer uploads a whole wedding, in full resolution",
    "catalogue_import": "a merchant imports a catalogue of 40,000 product photos",
    "camera_roll_sync": "a new app release syncs every user's camera roll",
    "photo_migration": "a migration re-processes old photos through the upload path",
    "db_lock": "a schema migration holds a lock: queries on the orders table wait",
    "partner_api": "the payment partner's API degrades",
    "dns_resolver": "the DNS resolver is slow: every new connection waits for it",
    "db_failover": "the database fails over: queries wait for the new primary",
    "month_end": "month end: finance exports every report at once",
    "dashboard_refresh": "a dashboard refreshes its export in every open tab",
    "partner_export": "a partner's nightly job pulls full exports",
    "scraper": "a scraper finds the export endpoint",
    "cache_refill": "a cache refill allocates millions of small objects",
    "big_import": "a bulk import builds huge object graphs",
    "memory_leak": "a leak in a library keeps growing the heap",
    "cgroup_throttle": "the container hits its CPU quota and is throttled",
}

STAGES = [
    StageText("Sync calls on the loop",
              "Challenge: a blocking call stops the whole loop: every request waits, health checks fail.",
              "Stage 1: await to_thread(call) instead of call()"),
    StageText("Offloaded to threads",
              "Challenge: the loop is free, but one GIL and no queue limit: work piles up for nobody.",
              "Stage 2: a bounded pool per kind of work; watch the lag"),
    StageText("Bounded executors",
              "Solved: CPU on processes, I/O on threads, a full queue answers 503, the lag is watched.",
              "All stages done"),
]

GOALS = {
    "lag": GoalText("Lag p99 < 50ms", "offload blocking calls"),
    "health": GoalText("Health fails = 0", "never block the loop"),
    "light": GoalText("Light p99 <100ms", "keep the loop free"),
    "served": GoalText("Heavy ok ≥ 70%", "CPU work on processes"),
    "queued": GoalText("Queued ≤ 50", "bound queues: 503 when full"),
    "watched": GoalText("Lag watched ≥90%", "start a lag watchdog"),
}

LEGEND = {"idle": "idle", "waits": "waits", "served": "served", "shed": "503 at once", "failed": "failed",
          "own": "loop work", "io": "blocking I/O", "cpu": "CPU work", "gil": "GIL wait", "gc": "GC pause",
          "budget": "lag budget", "incident": "incident"}

STRINGS = {
    "note_dots": "Dots are a sample, slowed down (cosmetic).",
    "note_chart": "The chart: the loop's worst lag each second, coloured by what held it.",
    # the pictures
    "blocked": "BLOCKED {ms:.0f}ms",
    "lane_state": "{state} {lag}",
    "lane_busy": "{state} +{n}",
    "cluster_state": "{state} · {pools}",
    "cluster_down": "{state}: restarting",
    "pool_threads": "threads {busy}/{n} +{q}",
    "pool_default": "default {busy}/{n} +{q}",
    "pool_procs": "procs {busy}/{n} +{q}",
    "no_pools": "no pools",
    "call_db": "a sync DB query",
    "call_http": "a sync HTTP call",
    "call_resize": "a resize",
    "call_report": "a json.dumps",
    "call_gc": "a GC pause",
    "call_own": "handler code",
    "call_pickle": "pickling",
    # incidents
    "uploads": "Upload batch",
    "slow_dep": "Slow dependency",
    "reports": "Report burst",
    "gc": "GC pauses",
    "uploads_start": "{cores:.1f} cores of image resizing: {cause}",
    "uploads_end": "the upload batch is done",
    "slow_dep_start": "sync DB and HTTP calls {times:.0f}x slower: {cause}",
    "slow_dep_end": "the dependency is fast again",
    "reports_start": "{cores:.1f} cores of json.dumps: {cause}",
    "reports_end": "the report burst is over",
    "gc_start": "the process stops ~{ms:.0f} ms, again and again: {cause}",
    "gc_end": "the GC pauses stop",
    "warn_killed": "killed: 3 health checks in a row timed out",
    "warn_stall": "{what} held the loop {ms:.0f} ms: nothing else ran",
    "warn_queued": "{n} calls queued in the executors, and growing",
    "warn_shed": "{n:.0f} requests answered 503 at once: a queue is full",
    "warn_watchdog": "your watchdog reports {ms:.0f} ms of loop lag",
    # the panel
    "tile_lag": "Lag",
    "tile_light": "p99",
    "tile_queued": "Queued",
    "toplist": "Requests",
    "bar_asked": "Asked",
    "bar_served": "Served",
    "bar_refused": "Refused",
    "limit_lag": "lag budget",
    "head_down": "Killed by the orchestrator: restarting, every request fails",
    "head_blocked": "{what} holds the loop: {ms:.0f} ms, nothing else runs",
    "head_lag": "Loop lag p99 {ms:.0f} ms: every request waits for it",
    "head_gc": "GC pauses stop the loop {ms:.0f} ms: no code of yours",
    "head_queued": "{n:,} calls queued: more than the pool can do in time",
    "head_shed": "{n} answered 503 at once: the pool is full",
    "head_gil": "CPU work in threads: the loop takes turns on the GIL",
    "head_ok": "Loop lag {ms:.0f} ms: the loop stays free",
}

LESSON = Lesson(
    title="Event loop blocking",
    one_liner="One asyncio loop runs every request: a blocking call inside it stalls them all. Offload "
              "blocking I/O to threads and CPU work to processes, bound every queue, and watch the loop's lag.",
    learn=(
        "asyncio runs every handler on one thread, the event loop. A handler only lets the others run when "
        "it awaits. A blocking call (a sync DB driver like psycopg2, requests, a Pillow resize, a big "
        "json.dumps) never awaits: while it runs, no other request moves, no timer fires, and the health "
        "check waits too. Three failed checks and the orchestrator kills a process that was merely busy.",
        "The symptom is event-loop lag: how late a callback runs compared with when it was due. Measure it "
        "with a watchdog (sleep 100 ms, see how late you wake up) and report it as a metric; asyncio's debug "
        "mode also logs every callback slower than loop.slow_callback_duration.",
        "asyncio.to_thread / loop.run_in_executor move a blocking call to a thread pool: the loop stays free. "
        "That is right for blocking I/O, which releases the GIL while it waits. CPU-bound Python code holds "
        "the GIL: eight threads still compute one at a time, and the loop thread must take turns with them "
        "(the interpreter switches every 5 ms, sys.getswitchinterval()). Free-threaded builds (PEP 703) "
        "change this, but most deployments still have a GIL.",
        "Give each kind of work its own executor: a ProcessPoolExecutor with one process per core for CPU "
        "work (each process has its own GIL; arguments are pickled to get there), a thread pool for blocking "
        "I/O. Separate pools are bulkheads: a slow database fills the I/O pool, not the one resizing images.",
        "Executors' queues have no limit. During a burst they grow for as long as it lasts, every call in them "
        "waits longer than its user does, and the work is still done for nobody. Bound each queue and refuse "
        "early (503 with Retry-After): a fast no beats a slow timeout.",
    ),
    watch_for=(
        "Sync calls on the loop: the loop node turns red, the gauge fills, BLOCKED counts up, then the door shuts: the instance is killed.",
        "Offloaded to threads: the loop stays green, but eight threads take turns on one GIL and the queue under the picture grows into the hundreds.",
        "Bounded executors: four processes compute at once, the I/O threads wait in parallel, and a full queue answers yellow 503s.",
    ),
    build=(
        ("Python: offload blocking I/O and CPU work to bounded pools",
         "io = ThreadPoolExecutor(max_workers=16)  # blocking I/O: threads that wait\n"
         "cpu = ProcessPoolExecutor(max_workers=os.cpu_count())  # CPU: a process per core\n"
         "MOST = {io: 16 + 32, cpu: 4 + 8}  # running + queued, at most\n"
         "in_flight = {io: 0, cpu: 0}\n"
         "\n"
         "async def run_blocking(fn, *args, cpu_bound=False):\n"
         "    pool = cpu if cpu_bound else io\n"
         "    if in_flight[pool] >= MOST[pool]:\n"
         "        raise HTTPException(503, headers={\"Retry-After\": \"2\"})\n"
         "    in_flight[pool] += 1\n"
         "    try:\n"
         "        loop = asyncio.get_running_loop()\n"
         "        return await loop.run_in_executor(pool, fn, *args)\n"
         "    finally:\n"
         "        in_flight[pool] -= 1"),
        ("Python: a loop-lag watchdog",
         "async def watchdog(every=0.1):\n"
         "    loop = asyncio.get_running_loop()\n"
         "    while True:\n"
         "        t = loop.time()\n"
         "        await asyncio.sleep(every)\n"
         "        LOOP_LAG.observe(loop.time() - t - every)  # a Prometheus histogram\n"
         "\n"
         "loop.slow_callback_duration = 0.05  # with PYTHONASYNCIODEBUG=1: log slow callbacks"),
        ("Kubernetes: a liveness probe that tolerates a short stall",
         "livenessProbe:\n"
         "  httpGet: {path: /health, port: 8080}\n"
         "  periodSeconds: 10\n"
         "  timeoutSeconds: 1\n"
         "  failureThreshold: 3"),
    ),
    checklist=(
        "No blocking call in an async handler: sync drivers, requests, time.sleep, big json.dumps, image work.",
        "Blocking I/O to a thread pool sized for waiting; CPU work to a process pool sized to the cores.",
        "One executor per kind of work (bulkheads), each with a bounded queue that answers 503 when full.",
        "Use async drivers where they exist (asyncpg, httpx.AsyncClient): no executor needed.",
        "Measure event-loop lag continuously and alert on it; turn on asyncio debug in staging.",
        "Keep health checks cheap, and their timeout and threshold above the worst stall you accept.",
        "Metrics: loop lag p99, executor queue length and wait, 503s, CPU per process, GC pause time.",
    ),
    refs=(
        Ref("Python: Developing with asyncio, running blocking code",
            "https://docs.python.org/3/library/asyncio-dev.html#running-blocking-code",
            "Why blocking code must not run on the loop, and debug mode's slow-callback log."),
        Ref("Python: loop.run_in_executor",
            "https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.run_in_executor",
            "Thread and process pools from asyncio, and asyncio.to_thread."),
        Ref("Python: concurrent.futures",
            "https://docs.python.org/3/library/concurrent.futures.html",
            "ThreadPoolExecutor and ProcessPoolExecutor, and what their defaults are."),
        Ref("David Beazley: talks on the Python GIL",
            "https://www.dabeaz.com/GIL/",
            "Why CPU-bound threads take turns, and how they slow down I/O threads."),
        Ref("Node.js: Don't Block the Event Loop",
            "https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop",
            "The same problem in another runtime: partitioning and offloading work."),
        Ref("Kubernetes: liveness, readiness and startup probes",
            "https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/",
            "How a probe's timeout and failure threshold decide when a busy container is killed."),
    ),
    try_next=(
        "Do stage 1 in labs/event_loop_blocking/main.py and watch the loop stay green while the queue grows.",
        "Do stage 2 and watch four processes compute at once, and the 503s when the queue is full.",
        "Set CPU_PROCESSES to 16 (more processes than cores) or CPU_QUEUE to 1000, and watch what changes.",
    ),
)

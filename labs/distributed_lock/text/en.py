"""Lab distributed_lock, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Distributed lock"
SUMMARY = "Workers take a lock before writing a shared report. Survive frozen, dead and late holders."
PARAMS = {"rate": "jobs per second (each one takes the lock and writes the report)"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"pause": "FREEZE", "wake": "WAKES", "crash": "CRASH", "back": "BACK", "delay": "DELAY",
         "lands": "LANDS", "cut": "CUT", "heal": "HEALED"}
CAUSES = {
    "gc_pause": "a stop-the-world garbage collection on a huge heap",
    "vm_migration": "its VM is being live-migrated to another host",
    "swapping": "the host ran out of memory and swapped it out",
    "cpu_throttle": "its container hit its CPU limit and is throttled",
    "oom_kill": "the kernel killed it for using too much memory",
    "kernel_panic": "a kernel panic after a driver update",
    "spot_reclaim": "the cloud took back its spot instance",
    "bad_deploy": "a bad deploy crashed it",
    "retransmits": "lost packets: TCP retransmits with backoff",
    "congested_link": "a congested link to the storage",
    "proxy_queue": "a proxy in front of the storage queued it",
    "switch_port": "a switch port to the lock service went down",
    "firewall_rule": "a firewall rule blocked the lock service's port",
    "dns": "a DNS change sent it to the wrong lock service address",
}

STAGES = [
    StageText("Plain lock",
              "Challenge: the lock never expires: a frozen or dead holder blocks every job. Use leases.",
              "Stage 1: a LEASE that expires, renewed by the holder"),
    StageText("Leases",
              "Challenge: a holder that froze wakes up, still sure it has the lock, and writes. Fence it.",
              "Stage 2: fencing tokens, checked by the storage"),
    StageText("Leases + fencing tokens",
              "Solved: a dead holder blocks for a lease at most, and late writes bounce off the storage.",
              "All stages done"),
]

GOALS = {
    "corrupt": GoalText("Corrupt writes = 0", "fencing tokens"),
    "stuck": GoalText("Stuck ≤ 5s", "a lease that expires"),
    "done": GoalText("Jobs done ≥ 80%", "renew; give up a lost lock"),
}

LEGEND = {"holder": "lock holder", "frozen": "frozen", "down": "dead / cut off", "lock_msg": "lock message",
          "write": "write", "late_write": "delayed write", "corrupt": "late write accepted",
          "refused": "late write refused"}

STRINGS = {
    # incidents
    "title_pause": "Pause",
    "title_crash": "Crash",
    "title_delay": "Late write",
    "title_partition": "Partition",
    "start_pause": "{worker} froze holding the lock: {cause}",
    "start_crash": "{worker} died holding the lock: {cause}",
    "start_delay": "a write from {worker} is stuck in the network: {cause}",
    "start_partition": "{worker} is cut off from the lock service: {cause}",
    "end_pause": "{worker} wakes up and carries on",
    "end_crash": "{worker} restarted",
    "end_delay": "the write from {worker} arrives at last",
    "end_partition": "{worker} reaches the lock service again",
    "warn_corrupt": "a late write from {worker} (job {job}) overwrote newer data",
    "warn_refused": "the storage refused a late write from {worker} (job {job})",
    # the panel
    "tile_corrupt": "Corrupt",
    "tile_stuck": "Stuck",
    "tile_done": "Done",
    "bar_jobs": "Jobs",
    "bar_lock": "Lock",
    "bar_writes": "Writes",
    "messages": "Messages",
    "head_corrupt": "{worker} wrote with a lost lock",
    "head_refused": "Storage refused a late {worker} write",
    "head_stuck": "No job done for {s:.0f}s: {worker} has it",
    "head_pause": "{worker} frozen with the lock",
    "head_crash": "{worker} died with the lock",
    "head_delay": "A write from {worker} is late",
    "head_partition": "{worker} cannot reach the lock",
    "head_ok": "One writer at a time",
    "note_chart": "Chart: lock messages (polling while it is taken) and writes per second.",
    # the pictures: the state under them (the lanes one: at most 13 letters)
    "state_corrupt": "CORRUPT WRITE",
    "state_refused": "STALE REFUSED",
    "state_stuck": "STUCK {s}s",
    "state_frozen": "{worker} FROZEN",
    "state_delayed": "WRITE DELAYED",
    "state_lock": "lock: {worker}",
    "nobody": "free",
    # the fan-in picture: the lock service (the door), the workers, the storage (the store)
    "fan_holds": "{worker} holds",
    "fan_frozen": "{worker} frozen",
    "fan_down": "{worker} down",
    "fan_cut": "{worker} cut off",
    "fan_token": "{state}  token {n}",
}

LESSON = Lesson(
    title="Distributed lock",
    one_liner="A lock needs a lease, so a dead holder cannot block forever, and a fencing token, so a late one cannot write.",
    learn=(
        "A distributed lock lets one worker at a time do something: regenerate a report, run a cron job "
        "once, own a shard. A lock service (ZooKeeper, etcd, Consul, Redis, a database row) hands it out.",
        "A lock that never expires is stuck the moment its holder dies, freezes or loses the network: nobody "
        "can tell a dead holder from a slow one. So locks are leases: the service takes the lock back after a "
        "TTL, and a holder that needs longer renews it.",
        "A lease is not enough. The holder can pause for longer than the TTL (a GC pause, a VM migration, "
        "swapping) or its write can sit in the network; meanwhile the lease runs out and another worker takes "
        "the lock. The first one carries on, sure it still holds the lock, and its write lands on top of "
        "newer data. Checking the clock before writing does not help: the pause can come right after the check.",
        "Fencing tokens fix it where the damage happens. Every grant comes with a number that only grows; the "
        "holder sends it with each write, and the storage refuses a write whose token is older than one it "
        "has already seen. The storage has to take part: a lock alone cannot stop a late write.",
        "Martin Kleppmann's 'How to do distributed locking' makes this case against Redlock: for safety you "
        "need fencing (and a consensus-backed lock service); for efficiency alone (avoid doing work twice), a "
        "simple lease is fine.",
    ),
    watch_for=(
        "Plain lock: a frozen holder turns the lock red; Stuck climbs for the whole pause, and a crash blocks forever.",
        "Leases: the lock comes back within ~2 s; but when the frozen worker wakes, its write bursts red by the storage.",
        "Leases + fencing: the same late write bursts orange: refused, because its token is older.",
        "Late write: the delayed write crawls to the storage in light orange, long after its job gave up.",
    ),
    build=(
        ("etcd (Go): a lease, a lock, and its revision as the fencing token",
         "s, _ := concurrency.NewSession(cli, concurrency.WithTTL(10)) // renewed while the process lives\n"
         "m := concurrency.NewMutex(s, \"/locks/report\")\n"
         "if err := m.Lock(ctx); err != nil { return err }\n"
         "token := m.Header().Revision // grows with every grant"),
        ("The storage checks the token (SQL)",
         "UPDATE reports SET body = $1, token = $2\n"
         " WHERE id = 7 AND token <= $2;  -- 0 rows updated: a stale holder, refuse"),
        ("Run a cron job under an etcd lock",
         "etcdctl lock --ttl=10 /locks/nightly-report ./regenerate-report.sh"),
    ),
    checklist=(
        "Decide what the lock is for: efficiency (a lease is enough) or correctness (you need fencing).",
        "Give every lock a TTL, renew it while working, and stop work when a renewal fails.",
        "Hand out a token that only grows (etcd revision, ZooKeeper zxid) and send it with every write.",
        "Make the storage refuse a write with an older token than it has seen.",
        "Take the lock from a consensus-backed service (etcd, ZooKeeper), not a single Redis.",
        "Test with long pauses, dead holders and slow networks, not only with crashes.",
    ),
    refs=(
        Ref("Martin Kleppmann: How to do distributed locking",
            "https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html",
            "Leases, GC pauses and fencing tokens; why Redlock is not safe for correctness."),
        Ref("Salvatore Sanfilippo: Is Redlock safe?",
            "http://antirez.com/news/101",
            "The Redis author's reply: the other side of the debate."),
        Ref("Redis: distributed locks",
            "https://redis.io/docs/latest/develop/use/patterns/distributed-locks/",
            "SET NX PX with a TTL, and the Redlock algorithm."),
        Ref("Google: The Chubby lock service",
            "https://research.google/pubs/the-chubby-lock-service-for-loosely-coupled-distributed-systems/",
            "Coarse-grained locks with leases, and sequencers: fencing tokens in production."),
        Ref("etcd: API (leases)",
            "https://etcd.io/docs/v3.5/learning/api/",
            "Leases with a TTL, keep-alives, and revisions that only grow."),
        Ref("ZooKeeper: recipes (locks)",
            "https://zookeeper.apache.org/doc/current/recipes.html",
            "Locks with ephemeral sequential nodes, which vanish with the session."),
    ),
    try_next=(
        "Do stage 1 in labs/distributed_lock/main.py and watch Stuck stay under 5 s in the first pause.",
        "Watch the frozen worker wake up at the end of it: where does its write land?",
        "Do stage 2 and watch the same write burst orange instead of red.",
        "Try a LEASE of 0.3 s: what happens to jobs that take longer than their lease?",
    ),
)

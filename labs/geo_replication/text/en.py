"""Lab geo_replication, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Geo-replication"
SUMMARY = "A profile service in three regions, oceans apart. Fast for everyone; survive losing a region."
PARAMS = {"rate": "user operations per second, all regions (20% writes)"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"down": "DOWN", "up": "BACK", "cut": "CUT", "joined": "JOINED", "slow": "SLOW", "normal": "NORMAL",
         "peak": "PEAK", "calm": "CALM"}
CAUSES = {
    "power": "a power failure takes its data centers down",
    "config_push": "a bad config push breaks every server in the region",
    "cloud_outage": "the cloud provider has a regional outage",
    "cooling": "a cooling failure shuts its data centers down",
    "fiber_cut": "a backbone fiber cut isolates it from the other regions",
    "bgp_leak": "a BGP route leak sends its inter-region traffic nowhere",
    "firewall": "a firewall rule push blocks traffic between regions",
    "cable_cut": "a subsea cable is cut: traffic takes a longer route",
    "congestion": "the link is congested at peak hours",
    "reroute": "a provider reroutes traffic the long way round",
    "morning": "it is morning there: everyone opens the app",
    "launch": "a product launch there",
    "tv_show": "a TV show there asks viewers to update their profile",
}

STAGES = [
    StageText("One primary region",
              "Challenge: far users cross an ocean for every read, and every write lives in us alone.",
              "Stage 1: a read replica in every region"),
    StageText("Read replicas",
              "Challenge: reads are fast, but users miss their own writes, and writes have one copy.",
              "Stage 2: writes in every region, two copies, session tokens"),
    StageText("Writes in every region",
              "Solved: local reads, one ocean per write, nothing missed or at risk, any region lost.",
              "All stages done"),
]

GOALS = {
    "read_p99": GoalText("Read p99 ≤ 50ms", "a replica in each region"),
    "write_p99": GoalText("Write p99 ≤ 400ms", "ack with the nearest copy"),
    "ryw": GoalText("Stale reads = 0", "fetch if token is newer"),
    "available": GoalText("Served ≥ 99%", "take writes in every region"),
    "at_risk": GoalText("Writes at risk = 0", "ack once 2 regions have it"),
}

LEGEND = {"fresh": "up to date", "behind": "behind", "down": "down", "request": "request",
          "far": "across an ocean / slow", "replication": "replication", "stale": "missed own write",
          "failed": "failed", "limit": "capacity"}

STRINGS = {
    # incidents
    "title_down": "Region down",
    "title_partition": "Cut off",
    "title_slow": "Slow link",
    "title_peak": "Peak",
    "down_start": "{name} goes dark: {cause}",
    "down_end": "{name} is back; its users return",
    "partition_start": "{name} is cut off from the other regions: {cause}",
    "partition_end": "{name} reaches the other regions again",
    "slow_start": "{a}–{b} link +{ms:.0f} ms, {loss:.0%} lost: {cause}",
    "slow_end": "the {a}–{b} link is back to normal",
    "peak_start": "{name} peak, {x:.1f}x its traffic: {cause}",
    "peak_end": "the {name} peak is over",
    "warn_stale": "a user missed their own write",
    "warn_failed": "{n} operations failed",
    "warn_risk": "{n} acknowledged writes in one region only",
    # the panel
    "tile_p99": "p99",
    "tile_stale": "Stale",
    "tile_available": "Served",
    "title": "Regions",
    "subtitle": "reads and writes served/s, last 1 s",
    "limit": "capacity {limit:.0f}/s",
    "head_stale": "{n} reads missed the user's own write in 5 s",
    "head_down": "{name} is down: its users go to {to}",
    "head_partition": "{name} is cut off: it cannot reach the others",
    "head_slow": "{a}–{b}: +{ms:.0f} ms, {loss:.0%} of messages lost",
    "head_peak": "{name} peak, {x:.1f}x: {busiest} at {util:.0%}",
    "head_far": "Users in {region} wait {p99} for a read (p99)",
    "head_ok": "Every region reads at home: p99 {p99}",
    "note_nodes": "Nodes: one column per region (us, eu, ap), three zones each.",
    "note_chart": "Chart: operations/s: fast, slow, missed own write, failed.",
    # the cluster picture: the state under the regions
    "state_down": "{name} DOWN · its users → {to}",
    "state_partition": "{name} CUT OFF",
    "state_slow": "{a}–{b} LINK +{ms:.0f} ms",
    "state_peak": "{name} PEAK {x:.1f}x",
    "state_ok": "ALL REGIONS UP · read p99 {p99}",
    "state_stale": "{n} MISSED OWN WRITE",
    # the lanes picture: states under the server, at most 13 letters
    "lanes_stale": "STALE READS",
    "lanes_down": "{name} DOWN",
    "lanes_cut": "{name} CUT OFF",
    "lanes_busy": "{name} AT {util:.0%}",
    "lanes_far": "p99 {p99}",
    # errors in your code
    "no_store": "RegionNode must keep its data in self.store, as {key: (version, value)}: the checker looks there",
}

LESSON = Lesson(
    title="Geo-replication",
    one_liner="Put a copy in every region for fast reads; acknowledge a write once two regions hold it; let "
              "session tokens keep users' own writes visible wherever they land.",
    learn=(
        "Light in fibre needs ~70 ms to cross the Atlantic and ~100-150 ms to cross the Pacific, one way. A service "
        "with one primary region makes every user far from it pay a round trip per request, and when that region "
        "goes down (power, a bad config push, a cloud outage) everything stops: reads, writes, everywhere.",
        "Read replicas in every region make reads local. The primary still takes every write and ships it to "
        "the replicas asynchronously: a write reaches them tens or hundreds of milliseconds later. A user in "
        "Europe who saves a setting and reloads can read the replica before the change arrives (read-your-writes "
        "broken). The primary's latest writes exist in one region only: lose it and they are gone (RPO > 0). "
        "And with the primary down, nobody can write.",
        "Writes in every region remove the single point of failure. Here each user's profile is written only by "
        "its owner, one request at a time, so conflicts are rare: the newest version wins (last writer wins). "
        "Acknowledge a write only once a second region holds it, the first of the other two to answer: one ocean "
        "crossing per write, never two, and no acknowledged write lives in one region only. That is the price of "
        "RPO = 0: ~140-300 ms per write, while reads stay local.",
        "Failover is a rule, not a hope: the load balancer sends a dead region's users to the next one, which "
        "takes their writes. The app also retries elsewhere and avoids a failing region for a few seconds, so "
        "a user's requests can land in different regions. A session token (the newest version the user has "
        "written or seen) lets any region tell whether its copy is new enough; if not, it fetches the newer one "
        "from another region, or refuses so the app retries. A region that was down or cut off catches up from "
        "hints: the writes it missed, re-sent until it acknowledges them.",
    ),
    watch_for=(
        "One primary: orange dots cross from eu and ap to us for every request; when us is cut off they "
        "die half way and the apps retry in us; when us turns red, every request fails.",
        "Read replicas: reads stay inside each column; blue batches cross to the replicas; purple answers when "
        "a user reads before their write arrived; with us down, writes fail.",
        "Writes everywhere: every write sends two blue dots and is answered at the first reply; a cut-off "
        "region's users write elsewhere, and its column turns orange (behind) until the hints arrive.",
        "Writes at risk: counted every 0.2 s by looking inside each region. Async replication always has some.",
    ),
    build=(
        ("Acknowledge after a second region (asyncio)",
         "self.keep(key, version, value)\n"
         "tasks = [asyncio.ensure_future(self.send_to(r, key, version, value)) for r in nearest(region)]\n"
         "for done in asyncio.as_completed(tasks):\n"
         "    if await done:\n"
         "        return True   # two regions hold it: safe to acknowledge\n"
         "return False          # only here: answer an error, the app retries elsewhere"),
        ("A session token on reads",
         "version, value = self.store.get(key, (0, None))\n"
         "if version < token:            # this user has written or seen something newer\n"
         "    found = await self.fetch(key, token)\n"
         "    if found is None:\n"
         "        return error(11)       # never answer older than the user's own write\n"
         "    version, value = found"),
        ("CockroachDB: survive the loss of a region",
         "ALTER DATABASE profiles SET PRIMARY REGION \"us-east1\";\n"
         "ALTER DATABASE profiles ADD REGION \"europe-west1\";\n"
         "ALTER DATABASE profiles ADD REGION \"asia-northeast1\";\n"
         "ALTER DATABASE profiles SURVIVE REGION FAILURE;\n"
         "ALTER TABLE users SET LOCALITY REGIONAL BY ROW;  -- each row homed where its user lives"),
    ),
    checklist=(
        "Measure p99 per region, not globally: the average hides the users an ocean away.",
        "Serve reads from a copy in the user's region; send only writes across oceans.",
        "Decide your RPO: acknowledge a write once a second region holds it if losing a region must lose nothing.",
        "Wait for the first other region, not all: one region down must not stop writes.",
        "Give every request a session token, and never answer older than it.",
        "Write the failover rule down: who takes a dead region's users, and who takes their writes.",
        "Fail back only once the region has caught up, or let the tokens catch it out.",
        "Resolve conflicts on purpose (owner-only writes, newest wins, or CRDTs), and test it with a partition.",
    ),
    refs=(
        Ref("AWS: Disaster recovery options in the cloud",
            "https://docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws/"
            "disaster-recovery-options-in-the-cloud.html",
            "Backup and restore, pilot light, warm standby, multi-site active/active: RPO and RTO."),
        Ref("Azure Cosmos DB: Consistency levels",
            "https://learn.microsoft.com/en-us/azure/cosmos-db/consistency-levels",
            "Session consistency: read-your-writes with session tokens, across regions."),
        Ref("Amazon DynamoDB global tables",
            "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GlobalTables.html",
            "Multi-region writes, last writer wins, and what a region failure loses."),
        Ref("CockroachDB: Multi-region survival goals",
            "https://www.cockroachlabs.com/docs/stable/multiregion-survival-goals",
            "Zone or region survival, and the write latency each one costs."),
        Ref("AWS: Disaster recovery architecture, part IV: multi-site active/active",
            "https://aws.amazon.com/blogs/architecture/disaster-recovery-dr-architecture-on-aws-part-iv-multi-site-active-active/",
            "Users served from every region at once, and moving them when one fails."),
        Ref("Terry et al.: Session guarantees for weakly consistent replicated data (1994)",
            "https://www.cs.cornell.edu/courses/cs734/2000FA/cached%20papers/SessionGuaranteesPDIS_1.html",
            "Read-your-writes and monotonic reads, kept with session state as clients move between servers."),
        Ref("Amazon Route 53: DNS failover",
            "https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/dns-failover.html",
            "Health checks, failover routing, and why DNS caches make failover gradual."),
    ),
    try_next=(
        "Do stage 1 in labs/geo_replication/main.py and watch the read p99 drop for eu and ap users.",
        "Then watch us get cut off: users miss their writes. Do stage 2 and watch the tokens catch it.",
        "Try --set rate=300: the regions get closer to their capacity during a peak.",
    ),
)

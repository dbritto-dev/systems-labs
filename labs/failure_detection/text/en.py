"""Lab failure_detection, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Failure detection"
SUMMARY = "8 nodes must agree who is dead: find a crash fast, never bury a slow or cut-off node."
PARAMS = {"rate": "client requests per second, routed by the cluster's view"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"crash": "CRASH", "back": "BACK", "slow": "SLOW", "fast": "FAST", "lossy": "LOSSY", "clean": "CLEAN",
         "cut": "CUT", "healed": "HEALED"}
CAUSES = {
    "oom_kill": "the kernel killed it for using too much memory",
    "kernel_panic": "a kernel panic after a driver update",
    "host_reboot": "its host rebooted for a hardware fault",
    "bad_deploy": "a bad deploy crashed it on start",
    "gc_pause": "long garbage-collection pauses",
    "noisy_neighbour": "a noisy neighbour is starving its CPU",
    "disk_full": "its disk is almost full and every write crawls",
    "bad_cable": "a damaged cable on its rack",
    "nic_firmware": "a buggy network card firmware",
    "duplex_mismatch": "a duplex mismatch on its switch port",
    "firewall_rule": "a new firewall rule blocks some of its peers",
    "stale_route": "a stale route sends some of its traffic nowhere",
    "security_group": "a security group change drops some of its peers",
}

STAGES = [
    StageText("Fixed timeout",
              "Challenge: a 1 s timeout buries healthy nodes behind lossy links. Learn each link.",
              "Stage 1: phi accrual: judge a silence by each peer's history"),
    StageText("Phi accrual",
              "Challenge: heartbeats to every peer cost 28 msgs/s per node. Probe one at a time.",
              "Stage 2: SWIM: ping one peer, indirect probes, suspect first"),
    StageText("SWIM",
              "Solved: crashes found in under 2.5 s, no healthy node declared dead, few messages.",
              "All stages done"),
]

GOALS = {
    "detect": GoalText("Found ≤ 2.5 s", "phi accrual: adapt per peer"),
    "false": GoalText("False deaths = 0", "phi, then indirect probes"),
    "msgs": GoalText("Msgs/node/s < 10", "SWIM: probe one peer"),
}

LEGEND = {"alive": "alive", "suspect": "suspected", "dead": "declared dead", "crashed": "crashed, not seen",
          "probe": "heartbeat or probe", "indirect": "indirect probe", "dropped": "lost", "limit": "limit"}

STRINGS = {
    # incidents
    "crashed": "{node} crashed: {cause}",
    "slowed": "{node} is {x:.0f}x slower: {cause}",
    "lossy": "{node} loses {share:.0%} of its messages: {cause}",
    "cut_off": "{node} cannot reach {peers}: {cause}",
    "back": "{node} is back",
    "fast": "{node} is fast again",
    "clean": "{node}'s links are clean again",
    "healed": "{node} reaches everyone again",
    "warn_false": "false deaths: {nodes}",
    # goals
    "no_crash": "no crash",
    "never": "never",
    # the panel
    "tile_found": "Found",
    "tile_false": "False",
    "tile_msgs": "Msgs/node",
    "bar_clients": "Clients",
    "bar_nodes": "Nodes",
    "messages": "Messages",
    "limit": "10/node",
    "chart_limit": "10/node",
    "head_false": "{node} declared dead, but alive",
    "head_unfound": "{node} down {s:.1f} s: not noticed",
    "head_found": "{node} down: found in {s:.1f} s",
    "head_slow": "{node} slow, still alive",
    "head_lossy": "{node} lossy, still alive",
    "head_partial": "{node} cut off in part, alive",
    "head_suspect": "{node} is suspected",
    "head_ok": "All alive, and the view agrees",
    "note_chart": "Chart: messages between nodes per second.",
    # the picture
    "state_sick": "{state}: {node}",
    "state_lossy": "LOSSY",
    "state_false": "FALSE DEATH: {node}",
    # the lanes picture (the clients' view): states under the cluster, at most 13 letters
    "lanes_failing": "FAILING",
    "lanes_needless": "NEEDLESS MOVE",
    "lanes_in_use": "{n}/{of} IN USE",
    # errors in your code
    "no_status": "Detector must keep self.status: a dict, peer id -> 'alive', 'suspect' or 'dead'",
}

LESSON = Lesson(
    title="Failure detection",
    one_liner="A silent node may be dead, slow, or behind a bad link: find crashes fast without burying the living.",
    learn=(
        "A node cannot tell a crashed peer from a slow one, or from a broken link: all it sees is silence. "
        "A failure detector turns silence into a verdict, and every detector trades how fast it finds a "
        "crash against how often it declares a healthy node dead.",
        "A fixed heartbeat timeout picks one point on that trade-off for every link: short, and lossy links "
        "bury healthy nodes; long, and every crash is found late.",
        "The phi accrual detector (Hayashibara et al., used by Cassandra and Akka) keeps each peer's recent "
        "heartbeat intervals and reports how unlikely the current silence is, given them. Steady links get "
        "fast verdicts; noisy links get the time their history asks for.",
        "SWIM (used by Consul, Serf and memberlist) stops heartbeating everyone: each node pings one peer per "
        "period, asks k others to ping it when it does not answer (one broken link is not a dead node), and "
        "suspects it before declaring it dead. The load per node stays the same however big the cluster.",
    ),
    watch_for=(
        "Fixed timeout: nodes behind the four lossy links keep turning red, and the False tile never stays at 0.",
        "Raise the timeout to 3 s: no more false deaths, but Found shows 3 s and the clients' requests fail meanwhile.",
        "Phi accrual: crashes found in under a second and lossy links tolerated, but 28 messages per node per "
        "second, and a partial partition still buries a node.",
        "SWIM: a few messages per node; indirect probes (light orange) route around a broken link.",
    ),
    build=(
        ("Cassandra: how suspicious a silence must be (cassandra.yaml)",
         "phi_convict_threshold: 12    # default 8; raise it on noisy networks such as EC2"),
        ("Akka: the phi accrual detector of a cluster (application.conf)",
         "akka.cluster.failure-detector {\n"
         "  threshold = 12.0\n"
         "  acceptable-heartbeat-pause = 3 s\n"
         "}"),
        ("HashiCorp memberlist (Go): SWIM with indirect probes",
         "cfg := memberlist.DefaultLANConfig()\n"
         "cfg.ProbeInterval = time.Second\n"
         "cfg.IndirectChecks = 3          // k helpers\n"
         "cfg.SuspicionMult = 4           // suspect this many probe periods (x log n) before dead"),
    ),
    checklist=(
        "Measure your heartbeat intervals per link before you pick a timeout: the tail matters, not the mean.",
        "Never let one observer's silence decide alone: ask others (indirect probes) or wait for agreement.",
        "Suspect before you declare dead, and let a suspected node refute it.",
        "Count the messages: all-to-all heartbeats grow with the square of the cluster.",
        "Alert on false deaths (nodes declared dead that come back alive), not only on real ones.",
    ),
    refs=(
        Ref("SWIM: Scalable Weakly-consistent Infection-style Process Group Membership Protocol",
            "https://www.cs.cornell.edu/projects/Quicksilver/public_pdfs/SWIM.pdf",
            "Das, Gupta and Motivala (2002): probes, indirect probes and suspicion."),
        Ref("The phi accrual failure detector",
            "https://dspace.jaist.ac.jp/dspace/bitstream/10119/4784/1/IS-RR-2004-010.pdf",
            "Hayashibara, Défago, Yared and Katayama (2004)."),
        Ref("Akka: phi accrual failure detector",
            "https://doc.akka.io/libraries/akka-core/current/typed/failure-detector.html",
            "How the threshold and acceptable pause shape detection in practice."),
        Ref("Lifeguard: local health awareness for more accurate failure detection",
            "https://arxiv.org/abs/1707.00788",
            "HashiCorp's improvements to SWIM, as used in Consul and Nomad."),
        Ref("Consul: gossip protocol",
            "https://developer.hashicorp.com/consul/docs/architecture/gossip",
            "SWIM-based membership and failure detection in production."),
    ),
    try_next=(
        "Watch stage 0, then set TIMEOUT = 3.0 in labs/failure_detection/main.py: what happens to Found?",
        "Do stage 1 (phi) and wait for a partial partition: who gets declared dead, and by whom?",
        "Do stage 2 and watch the indirect probes go around the broken links.",
    ),
)

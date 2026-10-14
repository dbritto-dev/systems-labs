"""Lab chain_replication, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Chain replication"
SUMMARY = "A key/value store on a chain of 4 nodes. Never read stale data, never lose an acknowledged write."
PARAMS = {"rate": "client operations per second (half writes, half reads)"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"crash": "CRASH", "slow": "SLOW", "join": "JOIN"}
CAUSES = {
    "kernel_panic": "a kernel panic after a driver update",
    "bad_deploy": "a bad deploy crashed it on start",
    "host_reboot": "its host rebooted for a kernel patch",
    "oom_kill": "the kernel killed it for using too much memory",
    "disk_failure": "its disk failed",
    "power_supply": "a power supply failed in its rack",
    "gc_pause": "long garbage-collection pauses",
    "disk_full": "its disk is almost full and every write crawls",
    "noisy_neighbour": "a noisy neighbour is starving its CPU",
}

STAGES = [
    StageText("Primary-backup",
              "Challenge: reads from backups miss acknowledged writes. Build a chain.",
              "Stage 1: writes flow head to tail, the tail acks; read the tail"),
    StageText("Chain",
              "Challenge: one dead node stalls the chain for good. Repair it.",
              "Stage 2: on a new chain, resend what you sent and never saw acked"),
    StageText("Chain + repair",
              "Solved: no stale reads, no lost writes, and the chain heals in a second.",
              "All stages done"),
]

GOALS = {
    "stale": GoalText("Stale reads = 0", "read from the tail"),
    "lost": GoalText("Lost writes = 0", "the tail acknowledges"),
    "outage": GoalText("Write outage ≤ 3s", "resend unacked on new chain"),
    "replicas": GoalText("In sync = 4", "tail keeps writes after copy"),
    "p99": GoalText("Write p99 ≤ 500ms", "don't wait for each write"),
}

LEGEND = {"request": "client request", "write": "write", "ack": "ack", "copy": "copy", "in_sync": "in sync",
          "behind": "behind", "slow": "slow", "down": "down / out", "limit": "writes in", "incident": "incident"}

STRINGS = {
    # incidents
    "head_start": "{node}, the head, crashed: {cause}",
    "middle_start": "{node}, in the middle of the chain, crashed: {cause}",
    "tail_start": "{node}, the tail, crashed: {cause}",
    "slow_start": "{node} is slow and backs up the chain: {cause}",
    "back": "{node} is back, empty: it copies the tail's state and joins as the tail",
    "warn_dropped": "the master drops {node} from the chain",
    "warn_ejected": "the master ejects {node}; it restarts empty",
    "warn_lost": "{n} acknowledged writes lost",
    "warn_stale_after": "{n} stale reads after {node} joined",
    # goal values
    "seconds": "{n} s",
    # the panel
    "title": "Writes and reads",
    "tile_stale": "Stale",
    "tile_lost": "Lost",
    "tile_writes": "Writes",
    "bar_writes": "Writes",
    "bar_reads": "Reads",
    "limit": "writes in",
    "head_chain": "Chain {chain}",
    "note_chart": "Chart: writes per second: fast, slow (over 0.5 s), failed.",
    # what the chain is going through: a phrase (cluster, headline) ...
    "sit_lost": "acknowledged writes lost",
    "sit_stale": "reads miss acknowledged writes",
    "sit_down": "{node} down: the master notices in 1 s",
    "sit_slow": "{node} slow: the chain backs up",
    "sit_stalled": "{n} writes stuck in the chain",
    "sit_copying": "{node} copies the tail's state",
    "sit_short": "{n} of {of} replicas",
    # ... and a word or two under the lanes picture's server, at most 13 letters
    "short_lost": "LOST WRITES",
    "short_stale": "STALE READS",
    "short_down": "{node} DOWN",
    "short_slow": "{node} SLOW",
    "short_stalled": "STALLED",
    "short_copying": "{node} COPYING",
    "short_short": "{n}/{of} REPLICAS",
    # the cluster picture: a word under each node
    "role": "{node} {role}",
    "role_head": "head",
    "role_tail": "tail",
    "role_down": "down",
    "role_copying": "copy",
    "role_out": "out",
    # errors in your code
    "no_store": "ChainNode must keep its data in self.store",
    "bad_read_from": "read_from returned {node!r}: it must return a node of the chain",
}

LESSON = Lesson(
    title="Chain replication",
    one_liner="Line the replicas up: writes enter at the head and leave at the tail; read the tail.",
    learn=(
        "Primary-backup with asynchronous replication answers a write before the backups have it. "
        "Reads from a backup can miss it (a stale read), and if the primary dies first, a write the "
        "client was told is safe is gone.",
        "Chain replication (van Renesse and Schneider, 2004) puts the replicas in a line. The head "
        "numbers each write and passes it on; every node applies it in order and passes it on; the "
        "tail applies it last and answers the client. Reads go to the tail: every write it holds is on "
        "every replica, so a read never sees a write that could be lost, and never misses an "
        "acknowledged one. That is strong consistency with one node answering reads.",
        "A configuration master (ZooKeeper, etcd, Chubby) decides who is in the chain. When a node "
        "dies, it drops it: the next node becomes the head, or the predecessor becomes the tail, or the "
        "predecessor of a dead middle node resends what it sent and never saw acknowledged.",
        "Each node keeps the writes it passed down until the tail's acknowledgement climbs back up "
        "(the paper's Sent list). That list is what makes every repair possible, and how a new node "
        "joins: it copies the tail's state, the tail keeps what it applies meanwhile, and resends it "
        "when the new node is its successor.",
        "Every write crosses every node, so the chain's latency is the sum of the hops, and one slow "
        "node slows every write: the master must eject a node that is slow, not only one that is dead.",
    ),
    watch_for=(
        "Primary-backup: the Stale tile turns red even with nothing broken; kill the head and Lost does too.",
        "A chain: nothing stale, nothing lost; but when n1 dies the writes stall for good (Writes ok 0%).",
        "Repair without keeping writes during a copy: the node that joins misses some and the chain stalls again.",
        "Chain + repair: a crash costs at most a second of writes; the copy (orange) flies to the new tail.",
    ),
    build=(
        ("The paper's Sent list, at every node but the tail",
         "sent[seq] = write; send(successor, write)    # passing it down\n"
         "del sent[s] for s <= ack.seq                 # the tail has it\n"
         "on a new successor: resend sent              # it drops what it has"),
        ("A chain in ZooKeeper: one ephemeral, sequential znode per replica",
         "create -e -s /chain/node- n3:7000    # the order is the chain; a dead session drops it"),
        ("Apply in order, whatever order the messages come in",
         "pending[w.seq] = w\n"
         "while self.seq + 1 in pending:\n"
         "    self.apply(pending.pop(self.seq + 1))"),
    ),
    checklist=(
        "Read from the tail (or ask the tail which version is committed before serving a read elsewhere).",
        "Number writes at the head and apply them in that order on every replica.",
        "Keep sent-but-not-acknowledged writes until the tail's ack comes back; resend them after a repair.",
        "Let a reliable master (ZooKeeper, etcd) own the membership, with session timeouts for dead nodes.",
        "Eject slow nodes too: one slow replica slows every write in a chain.",
        "Add a node at the tail only after it copied the state and the tail resent what came after.",
    ),
    refs=(
        Ref("van Renesse and Schneider: Chain Replication (OSDI 2004)",
            "https://www.usenix.org/legacy/event/osdi04/tech/full_papers/renesse/renesse.pdf",
            "The original paper: the protocol, the master, and every repair."),
        Ref("Terrace and Freedman: Object Storage on CRAQ (USENIX ATC 2009)",
            "https://www.usenix.org/legacy/event/usenix09/tech/full_papers/terrace/terrace.pdf",
            "Chain replication with reads from any node, still strongly consistent."),
        Ref("Apache ZooKeeper: recipes",
            "https://zookeeper.apache.org/doc/current/recipes.html",
            "Ephemeral sequential znodes: how a reliable master keeps the members and their order."),
        Ref("Jepsen: consistency models",
            "https://jepsen.io/consistency",
            "What 'never read stale data' means, precisely (linearizability)."),
    ),
    try_next=(
        "Do stage 1 in labs/chain_replication/main.py and watch the Stale tile stay at zero.",
        "Then wait for 0:20: what happens to the writes when n1 dies?",
        "Do stage 2 and watch the predecessor resend, and the copy fly to the node that joins.",
    ),
)

"""Lab paxos_consensus, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Paxos"
SUMMARY = "Paxos: 5 nodes agree on one log of commands while several propose at once, through crashes, loss and partitions."
PARAMS = {"rate": "client commands per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"crash": "CRASH", "back": "BACK", "lossy": "LOSSY", "clean": "CLEAN", "split": "SPLIT", "heal": "HEAL",
         "pause": "PAUSE", "wake": "WAKES"}
CAUSES = {
    "oom_killed": "the OOM killer stopped the process",
    "kernel_panic": "a kernel panic",
    "spot_reclaimed": "the cloud reclaimed its spot instance",
    "host_reboot": "the host rebooted for a security patch",
    "disk_failed": "its disk controller reset",
    "hypervisor_fault": "a hypervisor fault",
    "flapping_link": "a flapping link between the racks",
    "nic_firmware": "a buggy NIC firmware drops packets",
    "congested_link": "a congested link between the zones",
    "tor_switch": "a top-of-rack switch failed",
    "zone_link": "a cloud zone lost its link to the others",
    "firewall_rule": "a firewall rule blocked the cluster port",
    "gc_pause": "a stop-the-world GC pause",
    "vm_migration": "a live migration froze its VM",
    "disk_stall": "an fsync stalled on a busy disk",
}

STAGES = [
    StageText("First proposal wins",
              "Challenge: two nodes propose for one slot at once; nodes decide different commands.",
              "Stage 1: ballots, prepare/promise, then accept"),
    StageText("Paxos per slot",
              "Challenge: safe, but proposers duel and each command costs two round trips to all.",
              "Stage 2: one leader, phase 1 once, no-ops in gaps"),
    StageText("Multi-Paxos",
              "Solved: one log everywhere, nothing lost, one round trip per command.",
              "All stages done"),
]

GOALS = {
    "agree": GoalText("One log for all", "prepare and accept: ballots"),
    "kept": GoalText("Nothing lost", "adopt accepted values"),
    "live": GoalText("Decided < 2s 95%", "lead; back off at random"),
    "cheap": GoalText("Msgs/cmd ≤ 16", "skip phase 1 while leading"),
}

LEGEND = {"leader": "leader", "node": "node", "candidate": "candidate", "split": "decided differently",
          "down": "down", "request": "client command", "propose": "propose", "phase1": "prepare/promise",
          "phase2": "accept/accepted", "decide": "decide", "dropped": "lost"}

STRINGS = {
    # incidents
    "crashed_mid": "{node} crashed in the middle of a round: {cause}",
    "crashed": "{node} crashed: {cause}",
    "restarted": "{node} restarted with its disk",
    "cut_off": "{node} is cut off with {other}: {cause}",
    "whole": "the network is whole again",
    "paused": "{node} froze: {cause}",
    "woke": "{node} woke up, still sure it leads",
    "lossy": "the network loses {pct}% of messages: {cause}",
    "clean": "the network stops losing messages",
    "warn_split": "{n} slots decided two ways",
    "warn_lost": "{n} answered commands lost",
    # goal values
    "split_n": "{n} slots",
    "lost_n": "{n} lost",
    # the panel
    "tile_split": "Disagree",
    "tile_lost": "Lost",
    "tile_cost": "Msgs/cmd",
    "bar_clients": "Clients",
    "bar_nodes": "Nodes",
    "messages": "Messages",
    "head_split": "Slot {slot} decided two ways",
    "head_hit": "{node} is hit; {leader} leads, ballot {ballot}",
    "head_leader": "{leader} leads with ballot {ballot}",
    "head_duel": "No leader; proposers duel ({ballot})",
    "head_first": "No ballots: the first proposal heard wins",
    "note_chart": "Chart: messages between nodes per second.",
    # the cluster picture: under the grid
    "state_lossy": "LOSSY {pct}%",
    "state_paused": "PAUSED {node}",
    # the lanes picture (the clients' view): states under the cluster, at most 13 letters
    "lanes_split": "DISAGREE",
    "lanes_lost": "LOST",
    "lanes_stalled": "STALLED",
    # errors in your code
    "no_state": "PaxosNode must keep self.promised, self.accepted, self.decided and self.role (no {name})",
}

LESSON = Lesson(
    title="Paxos",
    one_liner="Agree on one value per log slot among 5 nodes, even when several propose at once: ballots, promises, and a majority.",
    learn=(
        "Why it is hard: two proposers send different values for the same slot at the same time. If "
        "each node keeps the first one it hears, some nodes decide one command and some the other, "
        "and the replicated log splits.",
        "Single-decree Paxos: a proposer picks a ballot higher than any it has seen and sends prepare. "
        "An acceptor promises to ignore lower ballots and reports the value it already accepted. With "
        "a majority of promises, the proposer must propose the accepted value with the highest ballot "
        "(it may already be chosen), else its own. A majority of accepts decides it. Any two "
        "majorities share a node, so a later ballot always finds a chosen value.",
        "Liveness: two proposers can keep outbidding each other forever (dueling proposers): each "
        "prepare cancels the other's accept. Paxos is always safe but only live with one proposer at "
        "a time; FLP says no deterministic protocol can promise both under asynchrony.",
        "Multi-Paxos: elect a leader with ballots (a random backoff breaks ties). It runs phase 1 once "
        "for every slot from its first undecided one, re-proposes what it learns and fills gaps with "
        "no-ops; then each command is one accept round. Chubby and Spanner run it; Raft is the same idea.",
    ),
    watch_for=(
        "First proposal wins: purple propose dots race; a node turns red when it decided a different command.",
        "Paxos per slot: orange prepare/promise dots on every command, and Msgs/cmd far above 16.",
        "Multi-Paxos: one green leader; only blue accepts and green decides, orange only after an incident.",
        "The first crash: the new leader re-proposes the two slots the old one got accepted, and fills the gap before them.",
    ),
    build=(
        ("The acceptor, the whole of Paxos's safety",
         "def on_prepare(self, ballot, slot):\n"
         "    if ballot > self.promised:\n"
         "        self.promised = ballot          # fsync before replying\n"
         "        return promise(self.accepted_from(slot))\n"
         "def on_accept(self, ballot, slot, value):\n"
         "    if ballot >= self.promised:\n"
         "        self.promised, self.accepted[slot] = ballot, (ballot, value)"),
        ("A proposer must adopt what it learns",
         "prior = [r.accepted[slot] for r in promises if slot in r.accepted]\n"
         "value = max(prior)[1] if prior else my_value   # highest ballot wins"),
    ),
    checklist=(
        "Persist promised and accepted before answering prepare or accept.",
        "Make ballots unique: (round, node id), and always pick one above any you have seen.",
        "Run phase 1 once per leadership for all slots, and fill gaps with no-ops.",
        "Randomize election timeouts and backoff so proposers do not duel forever.",
        "Apply the log in order, and make commands idempotent (clients retry).",
    ),
    refs=(
        Ref("Lamport: Paxos Made Simple (2001)",
            "https://lamport.azurewebsites.net/pubs/paxos-simple.pdf",
            "The algorithm in eleven pages, and Multi-Paxos in section 3."),
        Ref("Chandra, Griesemer, Redstone: Paxos Made Live (2007)",
            "https://static.googleusercontent.com/media/research.google.com/en//archive/paxos_made_live.pdf",
            "What it took to run Multi-Paxos in Google's Chubby."),
        Ref("Van Renesse, Altinbuken: Paxos Made Moderately Complex (2015)",
            "https://www.cs.cornell.edu/home/rvr/Paxos/paxos.pdf",
            "Multi-Paxos with leaders, slots and pseudocode for every role."),
        Ref("Howard: Distributed consensus revised (PhD thesis, 2019)",
            "https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-935.pdf",
            "Why any two quorums must intersect, and when they need not."),
        Ref("Wikipedia: Paxos (computer science)",
            "https://en.wikipedia.org/wiki/Paxos_(computer_science)",
            "The roles, the messages and the variants (Fast, Cheap, Byzantine)."),
    ),
    try_next=(
        "Do stage 1 in labs/paxos_consensus/main.py and watch the red nodes disappear.",
        "Then watch the messages per command, and the orange prepares on every command.",
        "Try --set rate=40: does stage 1 still decide in time, and does Multi-Paxos?",
    ),
)

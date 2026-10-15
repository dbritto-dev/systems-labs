"""Lab raft_consensus, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Raft"
SUMMARY = "Raft: elect one leader among 5 nodes and never lose a committed command, through crashes and partitions."
PARAMS = {"rate": "client commands per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"split": "SPLIT", "heal": "HEAL", "crash": "CRASH", "back": "BACK", "slow": "SLOW", "fast": "FAST"}
CAUSES = {
    "tor_switch": "a top-of-rack switch failed",
    "zone_link": "a cloud zone lost its link to the others",
    "firewall_rule": "a firewall rule blocked the cluster port",
    "kernel_panic": "a kernel panic",
    "oom_killed": "the OOM killer stopped the process",
    "host_reboot": "the host rebooted for a security patch",
    "congested_link": "a congested link between the racks",
    "noisy_neighbour": "a noisy neighbour is flooding the network",
}

STAGES = [
    StageText("No leader",
              "Challenge: nobody leads, so every command fails. Elect a leader with RequestVote.",
              "Stage 1: random election timeouts, RequestVote, heartbeats"),
    StageText("Leader election",
              "Challenge: the leader acks commands only it has. Replicate them to a majority first.",
              "Stage 2: AppendEntries, commit once a majority has the entry"),
    StageText("Log replication",
              "Challenge: after a partition heals, the old leader overwrites committed entries.",
              "Stage 3: step down on a higher term, reject stale leaders"),
    StageText("Safe",
              "Solved: one leader, every acked command on a majority, nothing lost through partitions.",
              "All stages done"),
]

GOALS = {
    "leader": GoalText("Has a leader", "elect one: RequestVote"),
    "election": GoalText("Elects < 2s", "time out and stand"),
    "committed": GoalText("Committed 99%", "ack after a majority"),
    "safe": GoalText("Nothing lost", "reject stale terms"),
    "available": GoalText("Available 95%", "redirect to the leader"),
}

LEGEND = {"leader": "leader", "follower": "follower", "candidate": "candidate", "down": "down",
          "request": "client command", "append": "AppendEntries", "vote": "RequestVote",
          "dropped": "dropped", "partition": "partition"}

STRINGS = {
    # incidents
    "cut_off": "{node} is cut off with {other}: {cause}",
    "whole": "the network is whole again",
    "crashed": "{node} crashed: {cause}",
    "restarted": "{node} restarted with its log",
    "slow": "the network is {x:.0f}x slower: {cause}",
    "fast": "the network is fast again",
    "warn_lost": "{n} committed commands lost",
    "warn_wrong": "{n} commands acked but never committed",
    # goal values
    "none": "none",
    "never": "never",
    "lost_n": "{n} lost",
    "wrong_n": "{n} not stored",
    # the panel
    "tile_leader": "Leader",
    "tile_term": "Term",
    "tile_lost": "Lost",
    "bar_clients": "Clients",
    "bar_nodes": "Nodes",
    "messages": "Messages",
    "head_split": "{node} cut off; {leader} leads term {term}",
    "head_down": "{node} is down; {leader} leads term {term}",
    "head_electing": "No leader: electing (term {term})",
    "head_ok": "{leader} leads term {term}",
    "note_chart": "Chart: messages between nodes per second.",
    # the lanes picture (the clients' view): states under the cluster, at most 13 letters
    "lanes_no_leader": "NO LEADER",
    "lanes_uncommitted": "UNCOMMITTED",
    "lanes_unanswered": "UNANSWERED",
    # the peers picture: under each node, its role and term (t: term), short
    "peer_leader": "{node} leader t{term}",
    "peer_candidate": "{node} cand t{term}",
    "peer_follower": "{node} t{term}",
    "peer_down": "{node} down",
    # errors in your code
    "no_state": "RaftNode must keep self.current_term, self.voted_for, self.log and self.role (no {name})",
}

LESSON = Lesson(
    title="Raft",
    one_liner="Agree on one ordered log across 5 nodes: one leader per term, and a command is safe once a majority has it.",
    learn=(
        "Terms and elections: time is split into terms, each with at most one leader. A follower that "
        "hears nothing for a random election timeout becomes a candidate, bumps the term and asks for "
        "votes; each node votes once per term, so only one candidate can win a majority.",
        "Log replication: the leader appends each command to its log and sends AppendEntries to the "
        "followers. Once a majority stores the entry it is committed, and only then does the leader "
        "answer the client. A leader that answers first loses the command when it crashes.",
        "Safety: a leader cut off in a minority cannot commit anything, but it does not know it is "
        "deposed. Every message carries the term: a node that sees a higher term steps down, and a "
        "node rejects AppendEntries from a lower term. Votes go only to candidates whose log is at "
        "least as up to date, so a new leader always has every committed entry.",
        "Availability: while a majority can talk, the cluster keeps working; the minority side stalls "
        "until the partition heals and then catches up from the new leader.",
    ),
    watch_for=(
        "No leader: every node stays blue, clients get redirects to nobody, and nothing commits.",
        "Leader election: one node turns green; when it crashes, orange dots (votes) elect another.",
        "Log replication: blue AppendEntries dots flow from the leader to every follower.",
        "Safe: during a split the old leader stays green but stalls; after HEAL it steps down at once.",
    ),
    build=(
        ("etcd: the Raft library behind Kubernetes",
         "import \"go.etcd.io/raft/v3\"\n"
         "n := raft.StartNode(&raft.Config{ID: 1, ElectionTick: 10, HeartbeatTick: 1,\n"
         "    Storage: storage, MaxSizePerMsg: 1 << 20, MaxInflightMsgs: 256}, peers)"),
        ("The rule that keeps it safe (on every message)",
         "if msg['term'] > self.current_term:\n"
         "    self.current_term, self.voted_for = msg['term'], None\n"
         "    self.role = 'follower'\n"
         "if msg['type'] == 'append_entries' and msg['term'] < self.current_term:\n"
         "    return reject(term=self.current_term)"),
    ),
    checklist=(
        "Persist current_term, voted_for and the log before answering any RPC.",
        "Randomize election timeouts (e.g. 150-300 ms) so candidates do not split the vote forever.",
        "Answer clients only after commit; let them retry with the same id (idempotent commands).",
        "Use an odd number of nodes: 5 survives 2 failures, 4 survives only 1.",
        "Test with partitions and crashes on, and check linearizability (Jepsen, Porcupine).",
    ),
    refs=(
        Ref("Ongaro and Ousterhout: In Search of an Understandable Consensus Algorithm (2014)",
            "https://raft.github.io/raft.pdf",
            "The Raft paper; figure 2 is the whole algorithm on one page."),
        Ref("raft.github.io",
            "https://raft.github.io/",
            "An interactive visualization, talks, and a list of implementations."),
        Ref("Ongaro: Consensus: Bridging Theory and Practice (PhD thesis, 2014)",
            "https://github.com/ongardie/dissertation",
            "Membership changes, log compaction, client interaction, and the proofs."),
        Ref("etcd-io/raft",
            "https://github.com/etcd-io/raft",
            "A production Raft library (etcd, Kubernetes, CockroachDB)."),
        Ref("Jepsen analyses",
            "https://jepsen.io/analyses",
            "How real consensus systems lost data under partitions, and why."),
    ),
    try_next=(
        "Do stage 1 in labs/raft_consensus/main.py and watch a leader turn green.",
        "Then watch the first split: does the old leader still answer clients on the small side?",
        "Try --set rate=40: does your leader batch entries into fewer AppendEntries?",
    ),
)

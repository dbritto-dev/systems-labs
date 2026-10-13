"""Lab broadcast, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Broadcast (Gossip Glomers #3)"
SUMMARY = "Gossip Glomers #3: get every number to all 25 nodes, through partitions, with few messages."
PARAMS = {"rate": "client operations per second (half broadcast, half read)"}

INCIDENT = IncidentText("Partition", "the partition", "the next partition")
VERBS = {"split": "SPLIT", "heal": "HEAL"}
CAUSES = {
    "tor_switch": "a top-of-rack switch failed",
    "zone_link": "a cloud zone lost its link to the others",
    "bgp_flap": "a BGP route flapped between the data centres",
    "firewall_rule": "a firewall rule blocked the cluster port on one node",
    "bad_nic": "one node's network card started dropping packets",
    "security_group": "a misconfigured security group cut one node off",
}

STAGES = [
    StageText("Single node",
              "Challenge: each node only knows the numbers sent to it. Tell the other nodes.",
              "Stage 1 (3b): send new numbers to your neighbours"),
    StageText("Multi-node",
              "Challenge: numbers sent during a partition never reach the other side. Retry them.",
              "Stage 2 (3c): re-send until the other node acknowledges"),
    StageText("Fault tolerant",
              "Challenge: it works, but costs too many messages and is too slow. Make it efficient.",
              "Stage 3 (3d): under 30 msgs/op, p50 < 400 ms, max < 600 ms"),
    StageText("Efficient",
              "Challenge: under 30 messages per operation. Now under 20: send numbers in batches.",
              "Stage 4 (3e): under 20 msgs/op (p50 < 1 s, max < 2 s)"),
    StageText("Batched",
              "Solved: every number reaches every node, through partitions, fast and in few messages.",
              "All stages done"),
]

GOALS = {
    "reach": GoalText("Reaches all", "send new numbers on"),
    "survive": GoalText("Survives split", "re-send until acked"),
    "msgs30": GoalText("Msgs/op < 30", "send fewer messages"),
    "fast": GoalText("Fast 400/600ms", "fewer hops per number"),
    "msgs20": GoalText("Msgs/op < 20", "batch the numbers"),
    "batched": GoalText("Fast 1s/2s", "batch more often"),
}

LEGEND = {"complete": "has every number", "missing": "missing some", "request": "client request",
          "message": "message", "dropped": "dropped", "partition": "partition", "limit": "limit"}

STRINGS = {
    # incidents
    "cut_off": "one node is cut off: {cause}",
    "split": "the cluster is split in two: {cause}",
    "whole": "the network is whole again",
    "warn_stuck": "{n} numbers stuck on one side",
    # goal values
    "lost": "lost",
    # the panel
    "tile_msgs": "Msgs/op",
    "tile_p50": "p50",
    "tile_behind": "Behind",
    "bar_clients": "Clients",
    "bar_nodes": "Nodes",
    "limit": "30 msgs/op",
    "chart_limit": "30/op",
    "messages": "Messages",
    "head_split": "Split {sizes}: {n} numbers wait",
    "head_behind": "{n} numbers not on every node yet",
    "head_ok": "Every number on every node (p50 {p50})",
    "note_chart": "Chart: messages between nodes per second.",
    # errors in your code
    "no_messages": "BroadcastNode must keep the numbers it has in self.messages",
}

LESSON = Lesson(
    title="Broadcast (Gossip Glomers #3)",
    one_liner="Get every number to every node of a cluster, even while the network is split, without flooding it.",
    learn=(
        "Gossip: a node that learns something new tells its neighbours, they tell theirs, and the news "
        "spreads to everyone in a few hops. Flooding every neighbour works, but sends the same number "
        "over every link.",
        "Partitions: messages across the cut are simply lost. Fire-and-forget gossip loses those numbers "
        "forever. Fault tolerance means keeping what the other side has not acknowledged and sending it "
        "again until it is (or periodically comparing what each side has: anti-entropy).",
        "Efficiency is a trade: fewer hops (send straight to everyone, or through a hub) cut latency; "
        "batching many numbers into one message cuts the message count, at the cost of waiting for the "
        "batch.",
        "Acknowledgements double the messages. Batching the acks too, and only re-sending what was not "
        "acknowledged, keeps fault tolerance cheap.",
    ),
    watch_for=(
        "Single node: only the node a client talked to has the number; the others stay orange.",
        "Multi-node: blue dots spread over the grid; during a partition red dots die at the cut.",
        "Fault tolerant: after the partition heals, the numbers flow across and the nodes turn blue.",
        "Efficient and batched: far fewer blue dots for the same numbers, and they still arrive fast.",
    ),
    build=(
        ("Maelstrom: run the real challenge against your own binary",
         "./maelstrom test -w broadcast --bin ./my-broadcast --node-count 25 \\\n"
         "    --time-limit 20 --rate 100 --latency 100 --nemesis partition"),
        ("Re-send until acknowledged (asyncio)",
         "async def push(self, dest, number):\n"
         "    while True:\n"
         "        try:\n"
         "            await self.rpc(dest, {'type': 'gossip', 'message': number}, timeout=0.5)\n"
         "            return\n"
         "        except TimeoutError:\n"
         "            await self.sleep(0.2)"),
    ),
    checklist=(
        "Know your fan-out: messages per update = nodes it reaches x (1 + acks).",
        "Never assume a message arrived: keep it until acknowledged, or repair with anti-entropy.",
        "Batch on the hot path; repair on a slow timer.",
        "Measure end-to-end: the time until every replica has it, not just the first hop.",
        "Test with partitions on, every time.",
    ),
    refs=(
        Ref("Fly.io: Gossip Glomers, challenge #3a Broadcast",
            "https://fly.io/dist-sys/3a/",
            "The original challenge and its parts 3b to 3e."),
        Ref("Maelstrom: the broadcast workload",
            "https://github.com/jepsen-io/maelstrom/blob/main/doc/workloads.md",
            "The messages and what the checker looks at."),
        Ref("Demers et al.: Epidemic algorithms for replicated database maintenance (1987)",
            "https://dl.acm.org/doi/10.1145/41840.41841",
            "Where gossip and anti-entropy come from."),
        Ref("Amazon Dynamo (2007)",
            "https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf",
            "Gossip for membership and anti-entropy with Merkle trees in production."),
    ),
    try_next=(
        "Do stage 1 in labs/broadcast/main.py and watch numbers spread across the grid.",
        "Then watch a partition: what happens to numbers sent on the small side?",
        "Try --set rate=60: does your batching get cheaper per operation?",
    ),
)

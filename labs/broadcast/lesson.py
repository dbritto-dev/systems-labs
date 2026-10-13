from core.lessons import Lesson, Ref

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

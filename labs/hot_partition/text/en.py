"""Lab hot_partition, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Hot partition"
SUMMARY = "A store sharded by key over 6 partitions. One key explodes: keep any partition from melting."
PARAMS = {"rate": "operations per second, usual traffic"}

INCIDENT = IncidentText("Hot key", "the hot key", "the next hot key")
VERBS = {"viral": "VIRAL", "link": "CLICKS", "sale": "SALE", "bot": "BOT", "calm": "CALM"}
CAUSES = {
    "celebrity_post": "a celebrity shared it with 80 million followers",
    "viral_video": "a video in it is going viral",
    "live_vote": "a TV show asks viewers to like it to vote",
    "breaking_news": "it is the first post about breaking news",
    "newsletter": "a newsletter with 2 million readers links to it",
    "push_notification": "a push notification sent it to every user",
    "homepage": "the homepage features it",
    "influencer": "an influencer put it in their bio",
    "flash_sale": "a flash sale opens on one product",
    "ticket_drop": "tickets for a stadium tour go on sale",
    "limited_sneaker": "a limited sneaker drops at noon",
    "price_glitch": "a price glitch spreads on social media",
    "scraper": "a scraper polls one product's page in a loop",
    "retry_loop": "a mobile app release retries one request in a loop",
    "health_check": "a misconfigured health check reads one id",
    "load_test": "someone load-tests production with one id",
}

STAGES = [
    StageText("Hash by key",
              "Challenge: one hot key melts its partition while the others idle. Split its writes.",
              "Stage 1: salt hot keys: spread their writes over sub-keys"),
    StageText("Salted hot keys",
              "Challenge: hot keys stay salted for good: every read fans in, long after they cool.",
              "Stage 2: salt only while hot; cache hot reads; fold back"),
    StageText("Adaptive salting",
              "Solved: hot keys spread while hot, reads come from a cache, no increment lost.",
              "All stages done"),
]

GOALS = {
    "busiest": GoalText("Busiest < 90%", "salt the hot key"),
    "throttled": GoalText("Throttled ≤ 1%", "salt the hot key"),
    "p99": GoalText("p99 ≤ 100ms", "salt; cache hot reads"),
    "correct": GoalText("Lost increments = 0", "read every sub-key; fold"),
    "fanin": GoalText("Req/op after ≤ 1.1x", "fold back when it cools"),
}

LEGEND = {"cool": "under 50%", "busy": "busy", "melting": "over 90%", "request": "request",
          "hot_key": "hot key", "fan_in": "fan-in", "cached": "cached", "throttled": "throttled",
          "limit": "capacity"}

STRINGS = {
    "fan_counters": "Counters",
    "fan_part": "p{p} {util:.0%}",
    # incidents
    "title_viral": "Viral post",
    "title_link": "Viral link",
    "title_sale": "Flash sale",
    "title_bot": "Bot",
    "viral_start": "{key} on p{p}: ~{rate:.0f} likes/s, {cause}",
    "link_start": "{key} on p{p}: ~{rate:.0f} clicks/s, {cause}",
    "sale_start": "{key} on p{p}: ~{rate:.0f} sales and views/s, {cause}",
    "bot_start": "{key} on p{p}: ~{rate:.0f} reads/s, {cause}",
    "start_plain": "one key gets ~{rate:.0f} operations/s: {cause}",
    "end": "{key} cools down",
    "end_plain": "the key cools down",
    "warn_throttled": "{n} operations throttled",
    # the panel
    "tile_busiest": "Busiest",
    "tile_throttled": "Refused",
    "tile_p99": "p99",
    "title": "Partitions",
    "subtitle": "requests/s, last 1 s",
    "limit": "capacity {limit:.0f}/s",
    "chart_limit": "capacity {limit:.0f}/s",
    "head_refused": "p{p} throttles {n} requests a second",
    "head_spread": "{key} over {n} partitions",
    "head_one": "{key} is hot, all on p{p}",
    "head_ok": "The busiest partition is at {util:.0%}",
    "note_nodes": "Nodes: p0-p5, coloured by utilisation.",
    "note_chart": "Chart: requests/s on the busiest partition.",
    # the pictures
    "state_melting": "p{p} MELTING {util:.0%}",
    "state_spread": "HOT KEY OVER {n} PARTITIONS, busiest {util:.0%}",
    "state_ok": "BALANCED, busiest {util:.0%}",
    # the lanes picture: states under the server, at most 13 letters
    "lanes_melting": "p{p} AT {util:.0%}",
    "lanes_spread": "SPREAD OVER {n}",
    "lanes_ok": "BUSIEST {util:.0%}",
    # errors in your code
    "stuck": "an incr() or read() has been running for over {seconds:.0f} s: does every await return?",
}

LESSON = Lesson(
    title="Hot partitions",
    one_liner="Hashing spreads keys, not traffic: one key that explodes melts its partition. Split it, cache it, "
              "fold it back.",
    learn=(
        "A store sharded by hash(key) puts every key on one partition. That spreads keys evenly, and with "
        "many keys of modest popularity it spreads the load too. But one key's traffic always lands on one "
        "partition: when a post goes viral or a bot hammers an id, that partition throttles and times out "
        "while the other five idle. Adding partitions does not help: the key is still on one of them.",
        "Write sharding (salting) splits a hot counter into N sub-keys, key#1 ... key#N, placed on different "
        "partitions. Each increment goes to one sub-key at random, so the writes spread N ways. A read must "
        "now fan in: read every sub-key and add them up. Miss one and increments are lost.",
        "Salting is not free. Every read of a salted key costs N requests, so salting a key that is read a "
        "lot, or keeping it salted after it cools, multiplies the load instead of spreading it. Salt only "
        "while a key is write-hot, pick N from its heat, and fold the sub-keys back into the key once it "
        "cools (stop writing to them, wait for writes in flight, then move their counts back).",
        "Hot reads need a different fix: a small cache in front of the store, for hot keys only, with a "
        "short TTL. A read at most half a second old is fine for a like counter, and the partition then sees "
        "two reads a second instead of four hundred.",
    ),
    watch_for=(
        "Hash by key: one node turns red, purple dots pour into it, red ones die half way; the others stay blue.",
        "Salted: the purple dots spread over all six nodes, but every read now sends six orange dots, and "
        "after the key cools the orange keeps coming (Requests/op after).",
        "Adaptive: the key spreads only while it is hot, a bot's reads come from the cache (blue at the "
        "door), and once it cools the orange stops.",
        "Lost increments: the store must hold exactly what was acknowledged. It is checked every half second.",
    ),
    build=(
        ("DynamoDB: write sharding for a hot counter (boto3)",
         "shard = random.randrange(N)\n"
         "table.update_item(Key={\"pk\": f\"{key}#{shard}\"},\n"
         "                  UpdateExpression=\"ADD likes :one\",\n"
         "                  ExpressionAttributeValues={\":one\": 1})\n"
         "# read: BatchGetItem every f\"{key}#{i}\" for i in range(N), and add them up"),
        ("Detect a hot key: count operations per key over the last quarter second",
         "times = recent.setdefault(key, deque())\n"
         "times.append(now)\n"
         "while times[0] <= now - 0.25:\n"
         "    times.popleft()\n"
         "rate = len(times) / 0.25  # operations per second"),
        ("Fold a cooled key back",
         "writing[key] = 1                 # new writes go to the key itself\n"
         "await asyncio.sleep(GRACE)       # writes already in flight to a sub-key land\n"
         "for i in range(1, width[key]):\n"
         "    await store.incr(key, await store.take(f\"{key}#{i}\"))\n"
         "width[key] = 1                   # reads stop fanning in"),
    ),
    checklist=(
        "Watch per-partition load, not the average: the average hides one melting partition.",
        "Find hot keys from recent counts (a sliding window, or a top-k sketch), per key, in real time.",
        "Salt write-hot keys over N sub-keys on different partitions; N from the heat, not a constant.",
        "Every read of a salted key reads every sub-key it may have written; changing N must not hide any.",
        "Cache read-hot keys for a short TTL, close to the clients; do not salt them.",
        "Fold sub-keys back when the key cools, after writes in flight have landed.",
        "Check the sums: what the store holds must equal what was acknowledged.",
    ),
    refs=(
        Ref("Amazon DynamoDB: Using write sharding to distribute workloads evenly",
            "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-sharding.html",
            "Random and calculated suffixes on a hot partition key."),
        Ref("Amazon DynamoDB: Burst and adaptive capacity",
            "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/burst-adaptive-capacity.html",
            "How DynamoDB isolates a hot item on its own partition, and where that stops."),
        Ref("Discord: How Discord stores trillions of messages",
            "https://discord.com/blog/how-discord-stores-trillions-of-messages",
            "Hot partitions in Cassandra and ScyllaDB, and request coalescing in front of them."),
        Ref("Scaling Memcache at Facebook (NSDI 2013)",
            "https://www.usenix.org/system/files/conference/nsdi13/nsdi13-final170_update.pdf",
            "Hot keys, leases against thundering herds, and replicating popular keys."),
        Ref("Cloud Bigtable: Schema design",
            "https://cloud.google.com/bigtable/docs/schema-design",
            "Row keys that spread writes, and the ones that pile them on one node."),
        Ref("Apache HBase reference guide: Rowkey design",
            "https://hbase.apache.org/book.html#rowkey.design",
            "Hotspotting, salting and hashing row keys."),
    ),
    try_next=(
        "Do stage 1 in labs/hot_partition/main.py and watch the next viral post spread over six partitions.",
        "Wait for a bot: salting does not help reads. Then do stage 2 and watch the cache take them.",
        "Try --set rate=250: the usual traffic leaves less room, and N matters more.",
    ),
)

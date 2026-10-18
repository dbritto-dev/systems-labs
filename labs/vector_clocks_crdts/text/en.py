"""Lab vector_clocks_crdts, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Vector clocks and CRDTs"
SUMMARY = "Multi-leader shopping carts on 5 replicas: keep every add and every remove through partitions."
PARAMS = {"rate": "device operations per second (add, remove or read a cart)"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"split": "SPLIT", "heal": "HEAL", "offline": "CUT", "back": "BACK", "skew": "CLOCK", "ntp": "NTP OK"}
CAUSES = {
    "tor_switch": "a top-of-rack switch rebooted after a firmware update",
    "zone_link": "the link between two data centres went down",
    "bgp_flap": "a BGP route flapped between the sites",
    "fiber_cut": "construction work cut the site's fibre",
    "vpn_cert": "the site-to-site VPN certificate expired",
    "isp_outage": "the site's internet provider went down",
    "ntp_step": "NTP stepped the clock after a long drift",
    "vm_migration": "a live VM migration left the clock off",
    "bad_ntp_server": "a misconfigured NTP server sent a wrong time",
}

STAGES = [
    StageText("Last write wins",
              "Challenge: carts edited in two places at once lose adds. Detect concurrent versions.",
              "Stage 1: vector clocks; keep concurrent siblings"),
    StageText("Vector clocks",
              "Challenge: nothing is lost, but removed items come back. Make the cart a CRDT.",
              "Stage 2: an observed-remove set (ORSet)"),
    StageText("CRDT",
              "Solved: every replica converges to the same cart: no lost adds, nothing comes back.",
              "All stages done"),
]

GOALS = {
    "lost": GoalText("Lost adds = 0", "vector clocks, not time"),
    "back": GoalText("Came back = 0", "an ORSet with tombstones"),
    "sync": GoalText("In sync ≥ 99%", "gossip every cart"),
    "msgs": GoalText("Msgs ≤ 150/s", "gossip less often"),
}

LEGEND = {"in_sync": "in sync", "diverged": "diverged", "lost": "lost add / item back", "request": "device request",
          "gossip": "gossip", "dropped": "dropped", "limit": "limit"}

STRINGS = {
    # incidents
    "split": "the network split {sides}: {cause}",
    "healed": "the network is whole again",
    "offline": "{node} is offline but keeps taking writes: {cause}",
    "online": "{node} is back online with old carts",
    "skew_ahead": "{node}'s clock jumped {s:.0f} s ahead: {cause}",
    "skew_behind": "{node}'s clock jumped {s:.0f} s back: {cause}",
    "ntp_fixed": "{node}'s clock is right again",
    "warn_lost": "{n} acknowledged adds vanished",
    "warn_back": "{n} removed items came back",
    # the panel
    "tile_lost": "Lost adds",
    "tile_back": "Came back",
    "tile_sync": "In sync",
    "bar_clients": "Devices",
    "bar_gossip": "Gossip",
    "messages": "Messages",
    "limit": "150/s",
    "chart_limit": "150/s",
    "head_lost": "{n} adds lost in the last 10 s",
    "head_back": "{n} removed items back in 10 s",
    "head_split": "Split {sizes}: both sides write",
    "head_offline": "{node} offline, still writing",
    "head_ahead": "{node}'s clock is {s:.0f} s ahead",
    "head_behind": "{node}'s clock is {s:.0f} s behind",
    "head_sync": "{share:.0%} of carts in sync",
    "head_ok": "All replicas hold the same carts",
    "note_chart": "Chart: messages between replicas per second.",
    # the picture
    "state_skew": "CLOCK {node} {s:+.0f} s",
    # the lanes picture (the devices' view): states under the server, at most 13 letters
    "lanes_lost": "ADDS LOST",
    "lanes_back": "ITEMS BACK",
    "lanes_skew": "CLOCK SKEW",
    # the peers picture: under each replica, how many carts differ there, or its clock, short
    "peer_differ": "{node}\n{n} differ",
    "peer_skew": "{node}\nclock {s:+.0f}s",
    # errors in your code
    "no_items": "CartNode needs an items(cart) method that returns the cart's items",
}

LESSON = Lesson(
    title="Vector clocks and CRDTs",
    one_liner="With many leaders, timestamps lose writes: track causality, or use data types that merge by themselves.",
    learn=(
        "Multi-leader (and offline-first) replication: every replica takes writes on its own and "
        "tells the others later. Two replicas can change the same cart at the same time, so the "
        "system must decide what to do with concurrent writes.",
        "Last write wins keeps the version with the newest timestamp and silently drops the other. "
        "Concurrent adds are lost, and wall clocks lie: after an NTP step an old write can beat a "
        "newer one. Cassandra and many caches work this way.",
        "A vector clock counts the writes each replica has seen ({n0: 3, n2: 1}). Comparing two of "
        "them says whether one version happened before the other or whether they are concurrent. "
        "Keep concurrent versions as siblings and merge them on read (Dynamo, Riak): nothing is lost, "
        "but a union brings back items one side had removed.",
        "A CRDT is a data type whose merge is commutative, associative and idempotent, so replicas "
        "that saw the same updates hold the same value, whatever the order. An observed-remove set "
        "tags every add uniquely and removes only the tags it has seen: an add the remover did not "
        "see survives, and nothing removed comes back. The price: tombstones to keep.",
    ),
    watch_for=(
        "Last write wins: when the network heals, one side's adds vanish (red); a clock jump does it too.",
        "Vector clocks: Lost adds stays at 0, but removed items come back after a split (Came back turns red).",
        "A set of removed items without tags loses re-adds: a product added again after a remove.",
        "ORSet: replicas diverge during a split (orange) and agree within a second of the heal.",
    ),
    build=(
        ("Riak: keep siblings (vector clocks), or let a CRDT set merge them",
         "riak-admin bucket-type create carts '{\"props\":{\"allow_mult\":true}}'\n"
         "riak-admin bucket-type create sets  '{\"props\":{\"datatype\":\"set\"}}'"),
        ("Automerge: a CRDT document per cart, merged in any order",
         "doc = Automerge.change(doc, d => { d.items.push(\"milk\") })\n"
         "merged = Automerge.merge(phoneDoc, laptopDoc)"),
        ("An ORSet remove: tombstone only the tags you have seen",
         "def remove(self, item):\n"
         "    self.removed |= self.tags.pop(item, set())"),
    ),
    checklist=(
        "Never order writes from different machines by wall-clock time alone.",
        "Decide per data type what concurrent writes mean: add wins, remove wins, or ask the user.",
        "Prefer a CRDT (counters, sets, maps) to hand-written sibling merges.",
        "Plan how tombstones are collected, and bound the size of what you gossip.",
        "Test with partitions, a replica offline for minutes, and a clock that jumps.",
    ),
    refs=(
        Ref("Amazon Dynamo (SOSP 2007)",
            "https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf",
            "The shopping cart, vector clocks, and siblings merged by the application."),
        Ref("A comprehensive study of CRDTs (Shapiro et al.)",
            "https://inria.hal.science/inria-00555588/document",
            "Counters, registers, sets (including the OR-set) and why their merges converge."),
        Ref("Riak KV: causal context",
            "https://docs.riak.com/riak/kv/latest/learn/concepts/causal-context/index.html",
            "Vector clocks, dotted version vectors and siblings in a real database."),
        Ref("Riak KV: sets",
            "https://docs.riak.com/riak/kv/latest/developing/data-types/sets/index.html",
            "A CRDT set you can use: adds and removes that merge by themselves."),
        Ref("Kyle Kingsbury: the trouble with timestamps",
            "https://aphyr.com/posts/299-the-trouble-with-timestamps",
            "How last-write-wins with wall clocks loses acknowledged writes."),
        Ref("Leslie Lamport: time, clocks, and the ordering of events",
            "https://lamport.azurewebsites.net/pubs/time-clocks.pdf",
            "Happened-before: the idea vector clocks are built on."),
    ),
    try_next=(
        "Do stage 1 in labs/vector_clocks_crdts/main.py and watch Lost adds stay at zero after a split.",
        "Then watch Came back: which removed items come back, and why?",
        "Do stage 2 and watch every replica converge, with nothing lost and nothing back.",
    ),
)

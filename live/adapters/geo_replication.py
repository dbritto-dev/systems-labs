"""The pictures for lab geo_replication: peers (the three regions on a triangle, the oceans between them as
links, the global load balancer as the door), cluster (the three regions as columns of nodes, with users'
requests and the messages that cross oceans between them) and lanes (the users' view: every
operation, the global load balancer as the door, the regions as the server)."""

from __future__ import annotations

import math

from live.adapters.common import client_lanes, every, link_list, op_id, peer_traffic
from live.canvas import BLUE, EXTRA2, GREEN, PURPLE, RED, WHITE
from live.views.base import adapts
from live.views.cluster import ClusterAdapter, ClusterFrame
from live.views.lanes import OUTLINE, LaneAdapter, LaneFrame
from live.views.lanes_peers import LINE, Leaf, PeersAdapter, PeersFrame

ZONES = 3  # nodes per region: a column each, one row per zone
USER_FLY = 0.25  # seconds a user's request is shown flying to its region (cosmetic: it takes ~1 ms)
DROP_FADE = 0.6  # seconds a dropped message or a failed request stays on screen
LONGEST = 1.2  # seconds: the longest a message between regions can be on the wire (a slow link)
MAX_USERS, MAX_MSGS, MAX_DROPS = 36, 60, 24


def node(region: int, k: int) -> int:
    """The node of a region in the 3x3 grid: column = region (us, eu, ap), row = one of its zones."""
    return (k % ZONES) * 3 + region


@adapts("geo_replication", "cluster")
class GeoReplicationCluster(ClusterAdapter):
    """The three regions side by side, us, eu and ap, as columns of three nodes (their zones), coloured
    by how many acknowledged writes the region still lacks: blue up to date, oranges behind, red down.
    A cut-off region is fenced by a red dashed line. Users' requests fly in from the left to the region
    that answers them: white at home, orange in another region (forwarded, failed over, retried).
    Between regions: orange a user's request forwarded across an ocean and its answer, blue replication,
    its acks and fetches,
    at their real speed (~70-150 ms); a message the network dropped dies half way in red."""

    def frame(self, variant: str, t: float) -> ClusterFrame:
        from labs.geo_replication.api import REGIONS
        from live.worlds.geo_replication import (
            MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC, MSG_USER, OP_END, OP_FIRST, OP_HOME, OP_OK, OP_SERVED,
            OP_START, REG_CUT,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return ClusterFrame()
        flights, drops = [], []
        for o in every(run.rows("ops", t - USER_FLY, t + 1e-9), MAX_USERS):
            to = o[OP_SERVED] if o[OP_SERVED] >= 0 else o[OP_FIRST]
            colour = WHITE if to == o[OP_HOME] else EXTRA2
            flights.append((-1, node(to, op_id(o[OP_START])), (t - o[OP_START]) / USER_FLY, colour))
        span = run.max_dur.get("ops", 0.0)
        failed = [o for o in run.rows("ops", t - DROP_FADE - span, t + 1e-9)
                  if not o[OP_OK] and t - DROP_FADE <= o[OP_END] <= t]
        for o in every(failed, MAX_DROPS // 2):
            drops.append((-1, node(o[OP_FIRST], op_id(o[OP_START])), (t - o[OP_END]) / DROP_FADE))
        moving, lost = [], []
        for k, m in enumerate(run.rows("msgs", t - LONGEST, t + 1e-9)):
            a, b = node(m[MSG_SRC], k), node(m[MSG_DEST], k + 1)
            if m[MSG_ARRIVED] is None:
                if t - m[MSG_SENT] <= DROP_FADE:
                    lost.append((a, b, (t - m[MSG_SENT]) / DROP_FADE))
            elif t < m[MSG_ARRIVED]:
                p = (t - m[MSG_SENT]) / max(1e-6, m[MSG_ARRIVED] - m[MSG_SENT])
                moving.append((a, b, p, EXTRA2 if m[MSG_USER] else BLUE))
        flights += every(moving, MAX_MSGS)
        drops += every(lost, MAX_DROPS)
        colours = w.region_colours(run, t)
        sample = w.sample_at(run, t)
        groups = None
        if sample is not None and any(sample[REG_CUT]):
            groups = [1 if sample[REG_CUT][i % 3] else 0 for i in range(3 * ZONES)]
        labels = [("", WHITE)] * (3 * (ZONES - 1)) + [(name, colours[i]) for i, name in enumerate(REGIONS)]
        return ClusterFrame(nodes=[colours[i % 3] for i in range(3 * ZONES)], groups=groups, flights=flights,
                            drops=drops, state=w.state_at(variant, t), labels=labels)


STALE_SHOWN = 1.0  # seconds a missed own write keeps the state purple


@adapts("geo_replication", "lanes")
class GeoReplicationLanes(LaneAdapter):
    """The users' view: every operation is a circle on the left, filled while it waits (white, then
    oranges). It flies to the door, the global load balancer (red while a region is down and its users
    are being moved). What came back fades there: green fast, orange slow (it crossed an ocean, or
    waited for a retry), purple a read that missed the user's own write, red failed. The server is the
    three regions: its gauge is the busiest region's load against its capacity."""

    def frame(self, variant: str, t: float, users: int) -> LaneFrame:
        from labs.geo_replication import lab
        from labs.geo_replication.api import REGIONS
        from live.worlds.geo_replication import (
            OP_END, OP_KIND, OP_STALE, OP_OK, READ, REG_CUT, REG_UP, judged, slow, worst_p99,
        )
        from live.worlds.base import fmt_ms

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return LaneFrame()

        def colour(o):
            return RED if not o[OP_OK] else PURPLE if o[OP_STALE] else EXTRA2 if slow(o) else GREEN

        waiting, flights, outcomes = client_lanes(run, t, users, "ops", 0, OP_END, colour=colour, rare_first=True)
        busy = w.busy(run, t)
        busiest = max(range(3), key=lambda i: busy[i])
        sample = w.sample_at(run, t)
        down = [i for i in range(3) if sample is not None and not sample[REG_UP][i]]
        cut = [i for i in range(3) if sample is not None and sample[REG_CUT][i]]
        last = w.recent(run, t, STALE_SHOWN)
        p99, _ = worst_p99(judged(run, [o for o in w.recent(run, t, 5.0) if o[OP_KIND] == READ]), READ, None)
        if any(o[OP_STALE] for o in last):
            state = (w.s("lanes_stale"), PURPLE)
        elif down:
            state = (w.s("lanes_down", name=REGIONS[down[0]]), RED)
        elif cut:
            state = (w.s("lanes_cut", name=REGIONS[cut[0]]), RED)
        elif busy[busiest] >= 0.9:
            state = (w.s("lanes_busy", name=REGIONS[busiest], util=busy[busiest]), EXTRA2)
        elif p99 is not None and p99 > lab.READ_P99_MAX:
            state = (w.s("lanes_far", p99=fmt_ms(p99) if p99 < math.inf else "∞"), EXTRA2)
        else:
            state = (w.screen.STATES["healthy"], GREEN)
        fill = busy[busiest]
        return LaneFrame(users=waiting, flights=flights, outcomes=outcomes,
                         door_color=RED if down else None, fill=fill,
                         gauge=RED if fill >= 0.9 else EXTRA2 if fill >= 0.7 else BLUE,
                         outline=RED if down or not all(o[OP_OK] for o in last) else OUTLINE, state=state)


# ---------------------------------------------------------------- the peers picture: the three regions, and the users


@adapts("geo_replication", "peers")
class GeoReplicationPeers(PeersAdapter):
    """The users, and the door: the global load balancer (red while a region is down and its users are being
    moved). The three regions on a triangle, us at the top, eu and ap below, each link labelled with its
    one-way latency over the ocean. A user's request flies from the door to the region that serves it: white
    to its home region, orange when failed over or retried elsewhere. On the links: orange a request
    forwarded across an ocean and its answer, blue replication (its acks and fetches too), each way on
    its own lane, keeping right. A box's gauge is the region's load against the 320/s it can
    serve (orange past 70%, red past 90%); its outline is the acknowledged writes it still lacks (blue, then
    oranges: "eu −120"), red while down ("us down"); a cut-off region's links are cut ("us cut off")."""

    def frame(self, variant: str, t: float, users: int) -> PeersFrame:
        from labs.geo_replication import scenario
        from labs.geo_replication.api import REGIONS, between
        from live.worlds.geo_replication import (
            MSG_ARRIVED, MSG_DEST, MSG_SENT, MSG_SRC, MSG_USER, OP_FIRST, OP_HOME, OP_SERVED, OP_START, REG_BEHIND,
            REG_CUT, REG_UP, behind_colour, hit_of,
        )

        w = self.world
        run = w.runs.get(variant)
        if run is None:
            return PeersFrame()
        lane = GeoReplicationLanes(w).frame(variant, t, users)  # the users, the balancer, the answers, the state
        flights, drops, recent = peer_traffic(run, t, (MSG_SENT, MSG_SRC, MSG_DEST, MSG_ARRIVED),
                                              lambda m: EXTRA2 if m[MSG_USER] else BLUE, longest=LONGEST,
                                              most=MAX_MSGS)
        for o in every(run.rows("ops", t - USER_FLY, t + 1e-9), MAX_USERS):
            to = o[OP_SERVED] if o[OP_SERVED] >= 0 else o[OP_FIRST]
            flights.append((-1, to, (t - o[OP_START]) / USER_FLY, WHITE if to == o[OP_HOME] else EXTRA2))
        sample = w.sample_at(run, t)
        up = sample[REG_UP] if sample is not None else (True,) * 3
        cut = sample[REG_CUT] if sample is not None else (False,) * 3
        behind = sample[REG_BEHIND] if sample is not None else (0,) * 3
        groups = [1 if c else 0 for c in cut] if any(cut) else None
        busy = w.busy(run, t)
        peers = []
        for i, name in enumerate(REGIONS):
            outline = behind_colour(behind[i]) if up[i] else RED
            # Down is red, and cut off has its links cut (✕): the words are the name, and how far behind it is.
            if up[i] and behind[i] > 2:
                label, words = w.s("peer_behind", name=name, n=behind[i]), outline
            else:
                label, words = name, outline
            fill = max(0.0, min(1.0, busy[i]))
            peers.append(Leaf(label=(label, words), short=name, tiny=name, fill=fill if up[i] else 0.0,
                              gauge=RED if fill >= 0.9 else EXTRA2 if fill >= 0.7 else BLUE, outline=outline))
        links = {(0, 1): LINE, (0, 2): LINE, (1, 2): LINE}  # the three oceans, always there
        links.update(recent)
        # Each link's one-way latency now: orange, and longer, while it is the slow link.
        inc = w.incident_at(variant, t)
        slow = scenario.LINKS[hit_of(run, inc)] if inc is not None and inc.kind == "slow" else ()
        labels = {}
        for a, b in links:
            extra = inc.severity if {REGIONS[a], REGIONS[b]} == set(slow) else 0.0
            ms = (between(REGIONS[a], REGIONS[b]) + extra) * 1000
            labels[a, b] = ((w.s("peer_ms_way", ms=ms), w.s("peer_ms", ms=ms)), EXTRA2 if extra else OUTLINE)
        return PeersFrame(users=lane.users, requests=lane.flights, outcomes=lane.outcomes, closed=lane.closed,
                          door_color=lane.door_color, state=lane.state, peers=peers, links=link_list(links),
                          link_labels=labels, groups=groups, flights=every(flights, MAX_MSGS + MAX_USERS),
                          drops=every(drops, MAX_DROPS), two_way=True)

# Lab: geo-replication

*[Leer en español](es/README.md)*

A profile and settings service runs in three regions, the US (`us`), Europe (`eu`) and Asia-Pacific
(`ap`), one `RegionNode` each, on a simulated network with real distances: ~1 ms inside a region,
~70 ms one way between us and eu, ~100 ms between us and ap, ~150 ms between eu and ap (±20%).
600 users, 200 living in each region, read and write their own profile and read other people's:
~200 operations a second, 20% writes; after saving, half of them look at their profile right away.
The global load balancer sends each user to their own region; when a region is down it moves its
users to the next one (us → eu, eu → us, ap → us) within ~1 s, and back 0.5 s after it recovers
(DNS caches make both gradual over 4 s). The user's app retries once, in the next region, on a
timeout (0.6 s) or an error, and avoids a region that failed it for 3 s. A region serves 320 reads
and writes a second.

At random times, like in production: a whole region goes down (a power failure, a bad config push,
a cloud outage, a cooling failure), a region is cut off from the other two while its users still
reach it (a fiber cut, a BGP leak, a firewall push), the link between two regions gets 150–350 ms
slower and drops 10% of its messages (a subsea cable cut), or a region has its peak (2.5–3x its
traffic). The run never restarts. The first incident is always us, the primary of stages 0 and 1, cut off from eu and ap at
0:20–0:32 (a fiber cut); its own users still reach it.

```
uv run python -m live geo_replication          # watch it; edit main.py and save
uv run python -m live geo_replication --lesson # the concept, links and a checklist
uv run pytest labs/geo_replication             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

Three pictures (`v` switches): **peers** (it opens with this one) shows the three regions on a
triangle, us at the top, each link labelled with its one-way latency; the users come in through the
global load balancer on the left (red while a region is down), and a user's request flies to the
region that serves it: white at home, orange elsewhere. On the links, each direction on its own
lane (keeping right): orange a request forwarded across an ocean and its answer, blue replication
(its acks and fetches too). A region's gauge is its load against the 320/s it can serve; its
outline and the word under it say how many acknowledged writes it lacks (`eu −120`), or that it is
down or cut off. **cluster** shows the regions side by side, us, eu and ap (named under each
column), as columns of three nodes (their zones), coloured by how many acknowledged writes the
region still lacks: blue up to date, oranges behind, red down; a cut-off region is fenced by a red
dashed line. Users' requests fly in from the left: white to their own region, orange to another.
Between the regions, at their real speed: orange a user's request forwarded across an ocean and its
answer, blue replication; a message the network dropped dies half way in red. **lanes** shows every operation on
the left, the global load balancer as the door (red while a region is down) and the regions as the
server, its gauge the busiest region's load; answers are green (fast), orange (slow: it crossed an
ocean or waited for a retry), purple (a read that missed the user's own write) or red (failed).

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 One primary region (given) | every region forwards every read and write to us | orange dots cross an ocean for every request from eu and ap (p99 ~180–250 ms); with us cut off, their requests wait for a timeout and a retry in us (p99 ~650 ms), and every write lives only in us; when us goes down, everything fails |
| 1 Read replicas | every region answers reads from its own copy; us acknowledges writes and `ship`s them in batches every 0.1 s (`on_replicate` keeps them) | reads stay home (p99 ~10–15 ms); but users who save and reload miss their change (purple), recent writes exist only in us (all of them while it is cut off), eu and ap writes wait for a retry across an ocean, and with us down nobody can write |
| 2 Writes in every region | any region takes a write and acknowledges it once the first of the other two holds it (`replicate`, `send_to`); missed writes become hints (`hand_off`); a read older than the session token `fetch`es the newer one | with us cut off, its users' writes are refused there and taken by eu, and their reads at home wait for the token instead of showing old data; with us down, eu takes its users; every goal OK |

Goals, judged per incident, on what happens from its start to 5 s after its end:

- **Read p99 ≤ 50 ms** and **write p99 ≤ 400 ms**, in the worst region, for users served in their
  own region (the users of a region that is down or cut off are served across an ocean whatever you
  do: they count for the other goals). A write may cross one ocean (eu → ap and back: ~300 ms), never
  two.
- **Stale reads = 0**: a read of a user's own profile that misses a write they were told was saved.
- **Served ≥ 99%** of all operations, after the app's one retry.
- **Writes at risk = 0**: every 0.2 s the checker looks inside each region's `store` and counts the
  acknowledged writes only one region holds. Those are what a region lost for good would take with
  it: asynchronous replication always has a few (RPO > 0). We count them, not "lost writes", because
  here a region comes back with its disk; in a real disaster it may not.

Why these choices:

- **Why one write per user, last writer wins.** A profile is written only by its owner, one request at
  a time, so two regions never take writes for the same key at once except around a failover, and then
  the newer version is the later write. That is why plain versions (here the commit time; in a real
  system a hybrid logical clock) are enough. Data written by many people at once (a shared document,
  a counter) needs per-key conflict resolution or CRDTs (see `vector_clocks_crdts`).
- **Why acknowledge after a second region, not all.** Waiting for every region makes one region down
  stop every write. Waiting for the first of the other two costs one ocean crossing and survives any one
  region: CockroachDB's "survive region failure", Spanner's multi-region configurations.
- **Why apply locally first, and refuse when alone.** A cut-off region still has users. If it acknowledged
  their writes, those writes would live there only (at risk), and other regions would accept conflicting
  ones. It keeps them, answers an error, and the app writes again in a region that can reach another.
- **Why session tokens.** The app moves a user between regions (failover, retries, avoiding a region
  that failed it), and a region that was down or cut off comes back behind. The token is the newest
  version the user wrote or saw; a region with an older copy fetches the newer one or refuses, never
  answers in the past.
- **Why hints.** A region that missed writes would stay behind until each key is written again; the
  others keep what it missed and re-send it every second until it acknowledges.

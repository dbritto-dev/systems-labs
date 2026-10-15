# systems-labs

*[Leer en español](README.es.md)*

Learn how backend and distributed systems behave by doing. There are **45 labs**, each
one problem: retries, load balancing, deadlines, autoscaling, caching, queries and indexes,
migrations, pagination, queues, outboxes, webhooks and sagas, streams, asyncio, deadlocks,
replication, partitioning, locks, consensus, and the Fly.io Gossip Glomers challenges. You
reproduce the problem, fix it in your own file, and **watch it live in the
terminal** while it runs. The tool assumes no topic: a lab about a cache plugs in
exactly like a lab about retries.

Pure Python: the standard library only, no runtime dependencies. Python 3.13+.

## Install and run

```sh
uv sync                                   # Python 3.13 + pytest
uv run python -m live                     # list the labs
uv run python -m live retry_storm         # watch one; edit its main.py and save
uv run python -m live retry_storm --lang es   # in Spanish: edit its es/main.py
uv run python -m live caching --lesson      # the concept, links and a checklist
uv run python -m live caching --at 90 --size 110x44 --color   # print one frame
uv run pytest                             # x = your code is not there yet, X = done
LABS_REFERENCE=1 uv run pytest            # check the reference solutions
LABS_STRICT=1 uv run pytest               # the repo's own check: starting-code tests stay strict
LABS_LANG=es uv run pytest                # your Spanish files (es/main.py)
```

More options: `--set name=value` changes a lab parameter (`--set rate=150`),
`--variant reference` watches the solution, `--variant path/to/file.py` watches any
file with the same names, `--seed N` picks other incident times, `--view NAME` opens
another picture of the lab (key `v` switches while it runs).

## Languages

Every lab runs in **English** or **Spanish**: `--lang es`, or `LABS_LANG=es` for
everything (the viewer, `--lesson`, the tests). Everything is translated, including the
file you edit: in Spanish you work in `labs/<lab>/es/main.py` (the same code and names,
with Spanish comments and hints; `es/reference.py` and `es/README.md` too).

The words live in catalogs, one per language, with the same names in each:

```
live/text/en.py, es.py           the screen: menus, panel titles, the loading screen…
core/text/en.py, es.py           messages from core/ (loading your code, --set)
labs/<lab>/text/en.py, es.py     one lab: title, stages, goals, incident causes, lesson…
```

A test (`core/test_i18n.py`) checks that every language has every name, key and
`{placeholder}`, and that the words fit the screen. The simulation never depends on the
language: a trace holds keys (a cause is `"bad_deploy"`), and only the screen turns them
into words. Adding a language: copy every `en.py` to `<code>.py`, translate, copy each
lab's `es/` folder to `<code>/`, and add the code to `core.i18n.LANGS`.

## How a lab works

- **Your file** is `labs/<lab>/main.py` (`labs/<lab>/es/main.py` in Spanish). It works
  at stage 0 and has docstring contracts, hints, and `NotImplementedError("TODO …")`
  stubs for the stages you build, in order, in that one file. `reference.py` has the
  same names, working.
- **Virtual time.** A lab is `asyncio` code on a virtual clock
  (`core.vtime.VirtualRun`): when nothing is ready, the clock jumps to the next
  timer. A minute of traffic runs in about a second, and always the same way.
- **One endless run.** A run is one simulation that never restarts until you quit,
  rerun or save: retry budgets, cache contents and queues carry on from minute to
  minute. It runs in a child process (your code never runs in the window's
  process), which hands the window the next minute in the background, with 20 s
  per minute before it is stopped. Errors show on screen with the file to edit.
  The window keeps the last 5 minutes to seek through, and totals forever.
- **Random incidents, like production.** Users keep coming (traffic drifts slowly,
  ±15%) and things go wrong at random: gaps vary, durations have a long tail,
  incidents cross minute boundaries, and each has a cause (a bad deploy, an
  expired certificate, a dead replica, a cache node restart…). The `retry_storm`
  service has full and partial outages; the `caching` lab's cache is emptied by deploys,
  restarts and failovers. Only the first incident is fixed (0:20), so the first
  verdict is stable; `--seed N` gives another production day.
- **Hot reload.** Save any file in `labs/<lab>/` (or press `r`): it reruns and plays
  from 0:00. The old picture stays until the new run arrives.
- **The stage is judged from what your code did**, never by reading it.

## The screen

```
Retry storm                                                      ▶ 1:40  1x   ← clock
Challenge: retries pile 4x the load on our service while it is down. …        ← what to fix
Behavior: Retry   → Stage 2: sleep backoff_delay(attempt) between retries
                                           ▍Load <1.5x ▍Retries ≥3% ▍Served ≥90%
 ○ ○ ● ○ ○                                    4.0x        75%          42%
 ○ ● ○ ○ ○   · ·  · ┃ ·   ┌─────────┐       ▃▃▃▃▃█      ▁▁▁▁▅█       ███▆▁
 ○ ○ ○ ○ ●           ┃     │ ▬▬▬   ▓ │      ▍Users  …   ▍Per second  …
                           └─────────┘      ▍Outage #2  ● OK / ● ALERT / ○ WAIT
                              DOWN          ▍Events  NEXT …   legend
 ▁▂▃▅█  chart: last 60 s per second, the limit dashed, incidents shaded
Edit labs/retry_storm/main.py and save: this window reruns it.
pause/resume [space] - restart [0] - rerun [r] - view [v] - quit [q]
```

- **Header**: the lab, the clock (`▶` playing, `❚❚` paused, `…` simulating ahead),
  the challenge for the stage your code is at, and the next step.
- **Picture (lanes)**: users on the left, one character each: dim `○` idle, `●`
  waiting, coloured by how much extra work their request costs (white = none,
  deeper orange = more). Dots travel to a **door** (whatever stands in front of the
  server: a gateway, a cache, a queue): solid red when closed, dotted when open.
  Outcomes fade at the door (green served, red failed). The server is a box with
  three drive bays and a gauge; its state is centred under it. Dots are a sample
  of the traffic, slowed down so you can see them: that part is cosmetic.
- **Tiles**: three numbers with their targets. The background is green when fine,
  orange when close, red only when a limit is crossed. The tiny bars underneath
  are the last 30 s: each is the worst second of its slice.
- **Users**: served, failed, waiting, and p50/p99 waits over the last 5 s.
- **Per second**: what users ask vs what the server gets, stacked by extra work,
  with the limit tick and a one-sentence headline.
- **Goals**: judged per incident (`Outage #3`, `Flush #3`), before / during /
  after it. `○ WAIT` until its window closes, `● OK`, or `● ALERT` (early only
  once it can no longer pass). Nothing is shown before the playhead reaches it.
- **Events**: newest first, with the latest open alert pinned with its fix, and a
  `NEXT` row naming the next check. Never anything that has not happened yet.
- **Chart**: the last 60 s, in the picture's colours, the limit dashed, incidents
  shaded.

Colours: white = first tries and normal requests; light, mid and deep orange =
extra work (a retry round, a cache miss, a duplicate load); red = failed; green =
served; blue = healthy/fixed.

Keys: `space` pause/resume, `0` restart from 0:00, `r` rerun, `v` the next picture (when
a lab has more than one), `q` quit, `← →` seek 5 s, `↑ ↓` speed, `d` a debug line (frame time, fps, how far the simulation is ahead). The screen needs at least 92x27 (else a one-line message), uses up to 124 columns, and looks best from 110x44 up.

## Labs

There are 45 labs. Each has two pictures, **lanes** (users, a door, a server) and **cluster**
(nodes and the messages between them), and opens with the one that teaches it best; press
`v` to switch. Some have a variation of lanes too: **relay** puts a second server in the
middle (a balancer, a gateway, a cache, a queue) with requests flying user → door → relay →
server, and **fan-out** has the relay call a few small servers, each with its own gauge (an
orchestrator and its services, a coordinator and its shards). **peers** stands the nodes on a
ring (a pentagon, an octagon), each a small box with its gauge and its name, with the links that
carry messages right now between them, and a red ✕ on every link a partition cuts.

Each of these labs opens with that picture.

| Picture | Labs |
|---|---|
| relay | `load_balancing`, `rate_limiting`, `graceful_shutdown`, `autoscaling`, `canary_releases`, `circuit_breaker`, `hedged_requests`, `connection_pool`, `idempotency`, `caching`, `cache_invalidation`, `n_plus_one_queries`, `zero_downtime_migration`, `message_queue_consumers` |
| fan-out | `saga_orchestration`, `webhook_delivery`, `two_phase_commit`, `hot_partition`, `replication_lag`, `quorum_replication` |
| peers | `raft_consensus`, `paxos_consensus`, `failure_detection`, `vector_clocks_crdts` |

Traffic and reliability:

| Lab | Problem | Stages |
|---|---|---|
| `retry_storm` | the service goes down; retries pile on | retry → backoff → jitter → retry budget |
| `rate_limiting` | a few clients flood the API | fixed window → token bucket → bucket + fair share |
| `connection_pool` | the database slows down or traffic spikes | pool → bounded pool → acquire timeout |
| `circuit_breaker` | one dependency gets very slow and takes the rest down | timeouts → bulkhead → circuit breaker |
| `overload` | a traffic spike; the queue never recovers (metastable) | bounded queue → skip late requests → adaptive LIFO |
| `load_balancing` | one of 8 servers turns slow but keeps its share | round robin → least outstanding → power of two choices |
| `hedged_requests` | rare slow replies set the p99; a replica gets slow | one call → hedge after p95 → hedge budget + cancel the loser |
| `deadline_propagation` | a chain of services keeps working after users give up | per-hop timeouts → pass the deadline down → skip late work |
| `graceful_shutdown` | deploys drop in-flight requests | exit at once → drain → readiness off first, then drain |
| `autoscaling` | traffic surges and drops; scale too late or flap | fixed fleet → CPU thresholds → target tracking with cooldown and warm-up |
| `canary_releases` | a bad build reaches users: crashes, errors, latency, one endpoint | deploy everywhere → fixed canary threshold → compare against a baseline, staged ramp, auto rollback |

Data and messaging:

| Lab | Problem | Stages |
|---|---|---|
| `caching` | a slow database; then a cache flush | cache-aside with TTL → single-flight + jittered TTLs |
| `cache_invalidation` | updates and cache fills race; stale values stick | cache then DB → write then delete → leased (versioned) fills |
| `idempotency` | payments get retried and arrive twice | replay stored answers → reserve the key before charging |
| `n_plus_one_queries` | a page asks the database once per item | N+1 → one batched IN query → one JOIN |
| `database_index` | the table keeps growing; every query reads all of it | hash index → hash + composite index |
| `keyset_pagination` | users page through a feed while rows come and go | OFFSET → keyset on created_at → opaque (created_at, id) cursor |
| `optimistic_locking` | many requests read, change and write the same rows | last write wins → version check → retry with re-read and jittered backoff |
| `zero_downtime_migration` | rename a column while old and new code both run | change in place → expand/contract → throttled batch backfill |
| `transactional_outbox` | save an order and announce it; the process dies in between | dual write → outbox + relay → idempotent consumer |
| `message_queue_consumers` | workers crash, jobs run slow, poison messages arrive | ack on receipt → ack after work + heartbeat → backoff + dead-letter queue |
| `saga_orchestration` | an order spans payments, stock and shipping; a step fails | no rollback → compensations → idempotent, resumable sagas |
| `stream_windowing` | count events per window when they arrive late | processing time → event time + watermarks → allowed lateness + updates |
| `webhook_delivery` | customer endpoints go down, hang, slow down or reject an event | fire once → retries with backoff → a queue per endpoint, ordered per key, parking |

Concurrency (asyncio and locks):

| Lab | Problem | Stages |
|---|---|---|
| `event_loop_blocking` | one blocking call stalls every request on the loop | sync calls → to_thread → bounded thread and process pools + a loop-lag watchdog |
| `async_backpressure` | a fast producer and a slow sink: memory grows until OOM | unbounded queues → bounded queues → credits, adaptive batches, counted shedding |
| `deadlock_avoidance` | transfers lock two accounts and the service freezes | lock in request order → timeouts with retry → one global lock order |

Distributed systems: the Fly.io [Gossip Glomers](https://fly.io/dist-sys/) challenges on a
simulated network with partitions:

| Lab | Challenge | Stages |
|---|---|---|
| `unique_id_generation` | #1 Echo, #2 Unique IDs | echo → unique ids → Snowflake ids (64-bit, time-ordered, survive clock steps) |
| `broadcast` | #3 Broadcast | multi-node → fault tolerant → efficient → batched (3b–3e) |
| `grow_only_counter` | #4 Grow-only counter | shared key → compare-and-swap → a key per node, on seq-kv |
| `kafka_style_log` | #5 Kafka-style log | single node → multi-node through lin-kv → efficient: an owner per key (5a–5c) |
| `transactions` | #6 Totally-available transactions | replicated → read uncommitted → read committed (6a–6c) |

Replication, partitioning and coordination, on the same network:

| Lab | Problem | Stages |
|---|---|---|
| `replication_lag` | reads go to replicas that lag behind | read your writes → monotonic reads |
| `consistent_hashing` | cache servers come and go; keys move | modulo → hash ring → ring + virtual nodes |
| `geo_replication` | users in 3 regions; a region fails or is cut off | one primary region → read replicas → writes in every region + session tokens |
| `hot_partition` | one key explodes and melts its partition | hash by key → salt hot keys → adaptive salting + hot-key cache |
| `quorum_replication` | every key on 3 of 5 nodes; a node goes down | one copy → quorums (R + W > N) → quorums + read repair |
| `chain_replication` | a chain of 4 replicas; a node crashes, slows down or joins | primary-backup → chain → chain with repair |
| `merkle_anti_entropy` | replicas silently drift: missed writes, bad disks, old backups | no repair → full scan → Merkle trees |
| `vector_clocks_crdts` | replicas take writes during a partition, then merge | last write wins → vector clocks → an OR-set CRDT |
| `failure_detection` | find a crashed node; never bury a slow one | fixed timeout → phi accrual → SWIM |
| `distributed_lock` | a lock holder freezes and wakes up still writing | plain lock → leases → fencing tokens |
| `two_phase_commit` | a transfer touches 3 shards; the coordinator crashes | one shard at a time → 2PC → 2PC with a decision log and recovery |
| `raft_consensus` | elect a leader; never lose a committed command | leader election → log replication → safe (terms, up-to-date votes) |
| `paxos_consensus` | several nodes propose; the leader crashes mid-round | first proposal wins → Paxos per slot → Multi-Paxos |

## Layout

```
core/   vtime.py (virtual-time asyncio)  services.py (fakeable downstreams)
        net.py (a Maelstrom-like network: nodes, RPC, latency, partitions, seq-kv/lin-kv)
        incidents.py (random incidents, drifting traffic)  contract.py (load lab code,
        discover labs, --set)  i18n.py (languages, catalogs)  text/ (core's words)
        lessons.py  testing.py
labs/   <lab>/ main.py  reference.py  README.md     your files, in English
               es/ main.py  reference.py  README.md  the same, in Spanish
               text/ en.py  es.py                    every word the lab shows
               scenario.py  lab.py (numbers, stage_of)  test_lab.py
live/   canvas.py (Braille + colour)  screen.py (terminal)  runner.py (child processes, Feed)
        frame.py (header, chart, footer)  panel.py (dashboard)  text/ (the screen's words)
        views/ (View, Adapter: lanes, cluster, and the lanes variations relay, fanout, peers)
        adapters/ (one module per lab)
        worlds/ (one World per lab)  viewer.py (the loop: play states, key commands, toasts,
        redraw only on change)  __main__.py  views/parts.py (the parts pictures are built from)
```

## Adding a lab

1. **`labs/<lab>/`** with:
   - `main.py`: stage 0 working, the rest as contracts and `NotImplementedError` stubs;
     `reference.py`: the same names, working; `README.md`;
   - `es/main.py`, `es/reference.py`, `es/README.md`: the same code and names, with
     Spanish comments and hints (a test checks the names match);
   - `text/en.py` and `text/es.py`: every word the lab shows: `TITLE`, `SUMMARY`,
     `PARAMS`, `INCIDENT` (an `IncidentText`), `VERBS`, `CAUSES`, `STAGES` (`StageText`),
     `GOALS` (`GoalText`), `LEGEND`, `STRINGS` (the rest, with `{placeholders}`) and
     `LESSON` (with links you have checked);
   - `scenario.py`: `stream(variant, seed=s, **params)` yields minute after minute of
     one endless run: `{"start": a, "end": b, "incidents": [(t0, t1, kind, severity,
     cause_key)], "tables": {name: [tuples]}}`, rows that started in [a, b), absolute
     times and ids. Use `core.vtime.VirtualRun`, `core.services` or `core.net`, and
     `core.incidents.schedule` (random incidents with a fixed first one);
   - `lab.py`: `META` (`id`, `params`: `{name: Param(default)}`), the numbers, `stage_of`;
   - `test_lab.py`: given behaviour passes; your-code tests use `@your_code(stage, …)`;
     compare stage indices (`world.stage_index(v)`), never words, so they pass in every
     language. A test that shows what the starting `main.py` gets wrong gets
     `@starting_code`: once you change `main.py` its failure becomes a skip, not a red test.
2. **A World** in `live/worlds/<lab>.py` (exported as `WORLD`) with these hooks. Its
   words come from the catalog: `self.s("key", ...)` (STRINGS), `self.word(key)`
   (VERBS), `self.cause(inc)` (CAUSES), `self.screen` (the screen's words):

   | Hook | Returns |
   |---|---|
   | `tables` | `{name: Table(sort, times)}`: the sort column and the time columns |
   | `ingest(run, tables, piece)` | adds per-second history (`run.add(name, t)`) |
   | `goals` | `[GoalSpec("", phase, "", window, measure, ok, doomed=None, key=...)]`: words from `GOALS[key]` |
   | `stage_colours`, `judge_stage(run, first)` | a colour per stage, and which stage the first incident shows |
   | `traffic(variant, t)` | `Traffic(tiles, bars, limit, limit_label, headline)` |
   | `user_stats(variant, t)` | `[(label, value, colour)]`; `self.request_stats(...)` does the usual one |
   | `stacks(variant)`, `chart_limit()` | per-second chart stacks, and the dashed limit |
   | `bands(variant, t)` | shaded spans (default: incidents that have started) |
   | `warnings(run, inc)`, `incident_text(inc, start)` | extra timeline events |
   | `legend` (with `LEGEND` keys), `legend_notes()` | one legend for the picture and the chart |
   | `incident_title(inc)`, `incident_verbs` (`VERBS` keys), `view` | names on screen; the picture it opens with (`"lanes"` unless you say otherwise) |

   The base class gives you `goal_lines`, `goal_title`, `next_check`, `timeline`,
   `stage(variant)`, the endless-run storage and settled-goal caching.
3. **An adapter per picture** in `live/adapters/<lab>.py` (every module there is
   imported). A lab can have several: each `@adapts(lab, view)` adds a picture the
   viewer can switch to with `v`; `World.view` is the one it opens with.
   ```python
   @adapts("my_lab", "lanes")              # users, a door, a server
   class MyLanes(LaneAdapter):
       def frame(self, variant, t, users) -> LaneFrame: ...

   @adapts("my_lab", "cluster")            # nodes, messages, partitions
   class MyCluster(ClusterAdapter):
       def frame(self, variant, t) -> ClusterFrame: ...
   ```
   Words in the picture (the state under the server) come from `self.world.screen.STATES`
   or the lab's `STRINGS`. A distributed lab's nodes are `core.net.Node` subclasses with
   `on_<type>` handlers; copy `labs/broadcast` to start one.
4. **A View** in `live/views/` only for a new kind of picture: subclass `View`, set
   `name`, implement `draw(cv, adapter, variant, t)`, and decorate it with `@register`.

## Performance

After 7 minutes a 110x44 frame renders in 2–4 ms; appending a minute takes
about 10 ms (retry_storm) to 30 ms (caching). Simulating a minute takes 0.1–1.3 s in
the child process, well ahead of the playhead.

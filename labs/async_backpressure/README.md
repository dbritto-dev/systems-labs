# Lab: async backpressure

*[Leer en español](es/README.md)*

An ingestion process built on asyncio. A firehose pushes ~1,000 events/s at it (30% HIGH: orders,
payments; 70% LOW: clicks, page views). Your `Pipeline` reads them (the source), parses them
(stage A), enriches them through a service (stage B: ~25 ms a call, 8 calls at once) and writes
them to a database in batches (stage C: 15 ms + 0.1 ms an event, one write at a time, at most
1,000 events). Memory is modelled: every event the process holds costs 4 KiB raw, 8 KiB parsed,
16 KiB enriched, on top of 96 MiB for the runtime; the container's limit is 256 MiB, and above
it the process is OOM-killed: every event in it is lost, and a new one starts 5 s later. While
nobody reads, the upstream keeps what arrives in its buffer (5,000 events, ~5 s) and drops the
oldest when it is full: lost, and nobody tells you. At random times, like in production, the sink
slows down 4–16x (autovacuum, a compaction, throttling, a backup), the enrichment service has a
latency spike (GC pauses, a cold cache), the upstream bursts 2–3x (a backfill, a viral moment), or
the sink is down for 4–12 s (a failover, an expired certificate). The run never restarts. The first
incident is always the sink 16x slower at 0:20–0:50.

```
uv run python -m live async_backpressure          # watch it; edit main.py and save
uv run python -m live async_backpressure --lesson # the concept, links and a checklist
uv run pytest labs/async_backpressure             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see in the first incident |
|---|---|---|
| 0 Unbounded queues (given) | `asyncio.Queue()` between the stages, writes of 50 | the queue in front of the sink grows ~13 MiB/s; ~12 s in the process is OOM-killed (2 kills, ~21,000 events lost), throughput ~20% of what the slow sink could take |
| 1 Bounded queues | `asyncio.Queue(maxsize=QUEUE_SIZE)`: `put` waits, the source stops reading | no OOM, memory flat (~51%); but the upstream's buffer overflows: ~19,000–20,000 events lost silently, and 50-event writes get ~29% of what the sink could take |
| 2 Credits + adaptive batches | `Credits` windows per link, `take_batch`, `admit` sheds LOW (counted) and keeps a reserve for HIGH | peak ~57%, 0 lost, ~500 LOW events/s shed (counted), every HIGH written, batches of 1,000, throughput 93–98%, p99 back to ~60 ms right after |

Goals, judged per incident: baseline ok (events written vs arrived, before), OOM kills = 0, lost = 0
(dropped upstream, killed with the process, or HIGH shed), peak memory ≤ 80% of the limit (these
three until 10 s after the incident), throughput ≥ 80% (events written vs what arrived, or the
slowest service's best if less), and the end-to-end p99 of the events arriving 5–20 s after the
incident < 1 s (it recovers).

Two pictures: `lanes` (opens first) shows one traced event in ten: it waits (white, then deeper
orange the longer it waits, upstream or in a queue), flies to the door (the source) when it is read,
and its fate fades there: green written, grey shed (LOW, counted), red lost. The door closes when
the source stops keeping up (the upstream holds a backlog) and turns red while the process restarts;
the server's gauge is the process's memory (orange above 80%). `cluster` puts the source, A, B, C
and the sink in one row: events fly along it, each stage is coloured by how many events it holds
(blue, then deeper orange) and labelled with that count, the source with what waits upstream, the
sink with its speed (or DOWN, or how many times slower); press `v` to switch.

- **Why an unbounded queue is a memory leak with a delay.** A queue between a fast stage and a
  slow one grows at the difference of their rates. 1,000 events/s in, 156/s out, 16 KiB each: 13 MiB
  a second, and the OOM killer does not ask which events matter.
- **Why bounded queues move the problem.** `put` waits, the waits travel back to the source, the
  source stops reading, and the backlog sits upstream. A durable log (Kafka) can wait for hours; a
  push firehose has a few seconds of buffer and then drops. Pausing is a choice that depends on the
  upstream: know which one you have.
- **Why credits.** A bounded queue bounds what waits, not what a stage holds in its hands (the batch
  being written, the calls in flight). Credits are granted back only when the events have moved on,
  so they bound both, and the source can ask how much room there is (`free`) instead of just blocking.
- **Why adaptive batches.** A write costs 15 ms plus 0.1 ms an event; slowed 16x, a batch of 50 takes
  320 ms (156 events/s) and a batch of 1,000 takes 1.8 s (543 events/s). Take what is queued: small
  batches when the sink is fast, big ones when it is slow.
- **Why shed LOW, counted.** When even full batches cannot keep up, something gives. Choose it: shed
  the low-priority class at the door, count it, and keep a reserve of the window so HIGH events still
  get in while the sink is down for a few seconds.

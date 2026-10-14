# Lab: stream windowing

*[Leer en español](es/README.md)*

A stream processor counts purchases per 10-second window for a live dashboard (and for
billing). Phones and servers make ~40 purchases a second; each event carries its event time
(when the purchase happened) and reaches the processor through a log with three partitions,
normally 0.05–1.5 s later and a little out of order. The processor calls your
`Windower.on_event(event, now)` for each one; you publish a window's count with
`self.sink.emit(start, count)` (emitting a window again replaces its count: an update), and
park events with `self.sink.side_output(event)`.

At random times, like in production, events arrive late: phones come back online and send
purchases made 6 s to a minute and a half ago (a subway, flight mode, a suspended app, a
carrier outage); one partition falls 5–20 s behind (a broker GC pause, a slow disk, a
rebalance, a hot partition); a producer's clock runs 10–45 s behind (NTP down, a resumed VM);
or a backfill replays events 1–3 minutes old. The first incident is always phones back online
at 0:20–0:30, with events 6–18 s old.

```
uv run python -m live stream_windowing            # watch it; edit main.py and save
uv run python -m live stream_windowing --lesson   # the concept, links and a checklist
uv run pytest labs/stream_windowing               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see (first incident, 12 seeds) |
|---|---|---|
| 0 Processing time (given) | count each event in the window open when it arrives | even in calm times stragglers land in the next window (98.9–99.7% in the right one); the late batch lands in the current window: 0–25% of windows exact, 206–287 events not in their window |
| 1 Event time + watermark | `watermark()` = largest event time seen − `ALLOWED_DELAY`; count by `event.time`; `close_ready()` emits a window once the watermark passes its end; later events are dropped (`self.dropped`) | calm windows exact (100%), first results 2.1–2.2 s after a window ends, but the late batch is dropped: 50% of windows exact, 164–249 events dropped |
| 2 Allowed lateness + updates | keep emitted windows (`self.fired`) until `too_late()`; a late event updates its window; a later one goes to `side_output`; `evict()` the rest | every window exact, 0 dropped, first results 2.1–2.3 s, at most 5 windows kept |

Two tempting shortcuts land on stage 1 too: a watermark as slow as the lateness
(`ALLOWED_DELAY = 32`) gets every window right but the first result comes 32 s after the
window ends; keeping every window forever (no `evict()`) gets them right but the state grows
without bound (8 windows by the first verdict, about 50 after ten minutes).

Goals, judged per incident: calm windows ≥ 99.9% (events that arrived in the 20 s before it,
counted in their own window; before); exact windows ≥ 99% (windows from 40 s before the
incident to 10 s after it whose latest count equals the events with that event time that
arrived within the allowed lateness; after, once they are final); dropped = 0 (events neither
in their window's count nor in the side output, in those windows and any window an event
arriving during the incident belongs to; after); latency p99 ≤ 5 s (from a window's end to its
first result, for windows ending during the incident; during); state ≤ 6 windows (the most
windows the processor kept, from the start of the incident until its windows are final;
during). The lab judges against its own watermark (largest event time seen − 2 s) and
lateness (30 s), the same numbers as `main.py`.

**Lanes picture** (the default). Phones on the left light up when their event arrives:
white on time, light to deep orange the later it is. Events fly to the door, which is the
processor's watermark: it turns solid red while late events are dropped, blue while late
events update closed windows, purple while too-late ones go to the side output. What happened
to each event fades at the door: green counted, blue counted in an update, purple side output,
red dropped or counted in the wrong window. The server is the windowed processor; its gauge is
the windows it keeps, against the limit of 6, and under it the watermark. The bars show the
latest windows by event time, split by what happened to their events; the chart shows events a
second the same way.

**Cluster picture.** Press `v` (or `--view cluster`) to see the pipeline as nodes on a 3x3
grid: the log's three partitions down the left (one turns orange while it lags), the processor
and the dashboard across the top, the processor's window state and the side output below them.
Producers send events to the partitions; events go on to the processor coloured by how late
they are; counts fly to the dashboard (green the first, blue an update) and too-late events to
the side output (purple). Dropped events die in red on their way in; the dashboard turns red
while a recent window is wrong, the state node orange or red as it reaches the limit.

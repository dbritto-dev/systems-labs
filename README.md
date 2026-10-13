# systems-labs

Learn how backend systems behave by doing. Each **lab** is one problem (retries,
caching, and later queues, databases, concurrency and distributed systems). You
reproduce the problem, fix it in your own file, and **watch it live in the
terminal** while it runs. The tool assumes no topic: a lab about a cache plugs in
exactly like a lab about retries.

Pure Python: the standard library only, no runtime dependencies. Python 3.13+.

## Install and run

```sh
uv sync                                   # Python 3.13 + pytest
uv run python -m live                     # list the labs
uv run python -m live retry_storm         # watch one; edit its main.py and save
uv run python -m live cache --lesson      # the concept, links and a checklist
uv run python -m live cache --at 90 --size 110x44 --color   # print one frame
uv run pytest                             # x = your code is not there yet, X = done
LABS_REFERENCE=1 uv run pytest            # check the reference solutions
```

More options: `--set name=value` changes a lab parameter (`--set rate=150`),
`--variant reference` watches the solution, `--variant path/to/file.py` watches any
file with the same names, `--seed N` picks other incident times.

## How a lab works

- **Your file** is `labs/<lab>/main.py`. It works at stage 0 and has docstring
  contracts, hints, and `NotImplementedError("TODO …")` stubs for the 2–3 stages
  you build, in order, in that one file. `reference.py` has the same names, working.
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
  service has full and partial outages; the `cache` is emptied by deploys,
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
pause/resume [space] - restart [0] - rerun [r] - quit [q]
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

Keys: `space` pause/resume, `0` restart from 0:00, `r` rerun, `q` quit, `← →` seek 5 s,
`↑ ↓` speed. The screen needs at least 92x27 (else a one-line message), uses up to 124 columns, and looks best from 110x44 up.

## Labs

| Lab | Problem | Stages |
|---|---|---|
| `retry_storm` | the service goes down; retries pile on | retry → backoff → jitter → retry budget |
| `cache` | a slow database; then a cache flush | cache-aside with TTL → single-flight + jittered TTLs |

## Layout

```
core/   vtime.py (virtual-time asyncio)  services.py (fakeable downstreams)
        contract.py (load lab code, discover labs, --set)  lessons.py  testing.py
labs/   <lab>/ main.py  reference.py  scenario.py  lab.py  lesson.py  test_lab.py  README.md
live/   canvas.py (Braille + colour)  screen.py (terminal)  runner.py (child processes, Feed)
        frame.py (header, chart, footer)  panel.py (dashboard)  views/ (View, Adapter, lanes)
        adapters/ (one LaneAdapter per lab)  worlds/ (one World per lab)  __main__.py
```

## Adding a lab

1. **`labs/<lab>/`** with:
   - `main.py`: stage 0 working, the rest as contracts and `NotImplementedError` stubs;
   - `reference.py`: the same names, working;
   - `scenario.py`: `stream(variant, seed=s, **params)` yields minute after minute of
     one endless run: `{"start": a, "end": b, "incidents": [(t0, t1, kind, severity,
     cause)], "tables": {name: [tuples]}}`, rows that started in [a, b), absolute
     times and ids. Use `core.vtime.VirtualRun`, `core.services`, and
     `core.incidents.schedule` (random incidents with a fixed first one);
   - `lab.py`: `META` (id, title, summary, params), the numbers, the goals' limits, the stages;
   - `lesson.py`: a `Lesson` with links you have checked;
   - `test_lab.py`: given behaviour passes; your-code tests use `@your_code(stage, …)`;
   - `README.md`.
2. **A World** in `live/worlds/<lab>.py` (exported as `WORLD`) with these hooks:

   | Hook | Returns |
   |---|---|
   | `tables` | `{name: Table(sort, times)}`: the sort column and the time columns |
   | `ingest(run, tables, piece)` | adds per-second history (`run.add(name, t)`) |
   | `goals` | `[GoalSpec(rule, phase, fix, window, measure, ok, doomed=None)]` |
   | `stages`, `judge_stage(run, first)` | the stages, and which one the first incident shows |
   | `traffic(variant, t)` | `Traffic(tiles, bars, limit, limit_label, headline)` |
   | `user_stats(variant, t)` | `[(label, value, colour)]` |
   | `stacks(variant)`, `chart_limit()` | per-second chart stacks, and the dashed limit |
   | `bands(variant, t)` | shaded spans (default: incidents that have started) |
   | `warnings(run, inc)`, `incident_text(inc, start)` | extra timeline events |
   | `legend`, `legend_notes()` | one legend for the picture and the chart |
   | `incident_name`, `incident_title(inc)`, `incident_verbs`, `files`, `view` | names on screen; `view = "lanes"` |

   The base class gives you `goal_lines`, `goal_title`, `next_check`, `timeline`,
   `stage(variant)`, the endless-run storage and settled-goal caching.
3. **A LaneAdapter** in `live/adapters/<lab>.py` (every module there is imported):
   ```python
   @adapts("my_lab", "lanes")
   class MyLanes(LaneAdapter):
       def frame(self, variant, t, users) -> LaneFrame: ...
   ```
4. **A View** in `live/views/` only for a new kind of picture: subclass `View`, set
   `name`, implement `draw(cv, adapter, variant, t)`, and decorate it with `@register`.

## Performance

After 7 minutes a 110x44 frame renders in 2–4 ms; appending a minute takes
about 10 ms (retry_storm) to 30 ms (cache). Simulating a minute takes 0.5–1.5 s in
the child process, well ahead of the playhead.

# Lab: retry storm

*[Leer en español](es/README.md)*

Users send ~100 requests/s (drifting slowly) through your `Client` to a service.
At random times, like in production, the service has a full outage (every call
fails fast: a bad deploy, a crashed node, an expired certificate…) or a partial
outage (40–85% of calls fail: a dead replica, a node out of memory…). Gaps and
durations vary, and the run never restarts. The first incident is always a full
outage at 0:20–0:30.

```
uv run python -m live retry_storm          # watch it; edit main.py and save
uv run python -m live retry_storm --lesson # the concept, links and a checklist
uv run pytest labs/retry_storm             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 No retry (given) | one call, no retry | users fail (red) while it is down |
| 1 Retry | retry `ServiceError` up to 3 times | retries come straight back: backoff 1.0x, and ~4x the load |
| 2 Retry + backoff | sleep `backoff_delay(attempt)`: `min(cap, base * 2**attempt)` | waits double each round (2.0x), but every user waits the same: jitter 0% |
| 3 Retry + backoff + jitter | make `backoff_delay` random between 0 and the backoff | retries spread out (jitter ~58%), but the load is still ~4x |
| 4 Retry + backoff + jitter + budget | spend a `RetryBudget` token (10%) on every retry | load stays ~1.1x; every goal OK |

Goals, judged per outage (full or partial): baseline ok (before), retries ≥ 3% of calls
(during), backoff ≥ 1.5x (during), jitter ≥ 25% (during), load < 1.5x the 15 s before
(during), served ≥ 90% of requests started in the 5 s after.

- **Backoff** is how much the average wait grows from one retry round to the next. Retrying
  straight away or every 50 ms is about 1x; exponential backoff is about 2x. When a budget
  stops most requests before a second retry, there is nothing to compare: it shows "few"
  and passes.
- **Jitter** is how much the wait before the *same* retry round varies between users
  (standard deviation / mean). Fixed gaps and plain exponential backoff are both 0%: every
  user comes back at the same moment. Full jitter is about 58%.

**Pictures:** `lanes` (the default) and `cluster`: clients → your `Client` → the service, with failed calls dying red between them. Press `v` to switch, or start with `--view cluster`.

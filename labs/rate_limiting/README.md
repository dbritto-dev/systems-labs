# Lab: rate limiting

*[Leer en español](es/README.md)*

20 clients call an API through your `RateLimiter`. The backend does 15 requests at a
time, 100 ms each (150 requests/s); beyond that requests wait in a short queue, and a
full queue turns them away (503). Normally the clients send ~100 requests/s together.

At random times, like in production, a few clients flood the API in bursts: a batch job
sending its work in chunks, a scraper timing its bursts to the window reset, an SDK
release with a retry bug. The first flood is always 5 clients at 0:20–0:35. The run
never restarts.

```
uv run python -m live rate_limiting            # watch it; edit main.py and save
uv run python -m live rate_limiting --lesson   # the concept, links and a checklist
uv run pytest labs/rate_limiting               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` (`RateLimiter.allow`) | What you see |
|---|---|---|
| 0 No limit (given) | let everything through | the backend overloads; clients that did nothing wrong fail too |
| 1 Fixed window | at most `rate` (20) per client in each 1 s window | the flood is turned away, but a burst straddling a reset gets 2x through |
| 2 Token bucket | per client: refill 20 tokens/s, up to 10 | smooth (peak 1.4x), yet 5 capped clients together still swamp the backend |
| 3 Bucket + fair share | refill at min(rate, capacity / active clients) | the flood gets its fair share; everyone else is served |

Goals, judged per flood: baseline ok (before); the flooding clients' requests limited
≥ 50% (during); peak ≤ 1.6x (the most one flooding client gets through in any 1 s,
vs its rate) (during); the other clients served ≥ 99% (during); served ≥ 97% in the
5 s after, for the clients that did not flood.

**Pictures:** `lanes` (the default) and `cluster`: clients → the rate limiter → the backend; limited requests die red before the limiter, 503s after it. Press `v` to switch, or start with `--view cluster`.

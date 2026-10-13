# Lab: circuit breaker

Our service takes ~100 requests/s with a pool of 24 workers. Each request holds a
worker while it calls ONE dependency through your `Client`: "payments" (60%) or
"recs" (40%). At random times, like in production, one dependency gets very slow:
4–10 s a call (a GC storm, a lock, a network brownout, a provider rate-limiting us).
Users give up after 2 s, but the server does not know: its worker keeps waiting. The
first incident is always "recs", 8 s a call, at 0:20–0:30.

```
uv run python -m live circuit_breaker            # watch it; edit main.py and save
uv run python -m live circuit_breaker --lesson   # the concept, links and a checklist
uv run pytest labs/circuit_breaker               # x = not yet, X = done
```

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 No protection (given) | calls wait as long as they take | Workers 24/24, and the healthy dependency fails too (~5% served) |
| 1 Timeouts | `asyncio.timeout(TIMEOUT)` around the call | calls stop at 1 s, but the pool still fills: healthy ~15–70% |
| 2 Timeouts + bulkhead | a `Bulkhead(10)` per dependency | the healthy dependency is fine; users of the slow one still wait 1 s to fail |
| 3 Timeouts + bulkhead + breaker | a `CircuitBreaker` per dependency | the door shuts: calls fail in under 1 ms, and it closes again after |

Goals, judged per slowdown: baseline ok (before); calls to the slow dependency ≤ 1.2 s
(p99, during); requests to the healthy dependency served ≥ 99% (during); requests to the
slow one fail fast, p99 < 50 ms once it has been slow for 3 s (during); requests to it are
served again ≥ 95% from 7 s after it is back (after).

The chart shows busy workers each second (white: calls to a healthy dependency; orange:
calls to the slow one), against the pool size.

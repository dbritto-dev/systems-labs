"""Lab circuit_breaker: YOUR FILE. Edit it and save; the live window reruns it.

Our service takes ~100 requests/s with a pool of 30 workers. Each request
holds a worker while it calls ONE dependency through your `Client`:
"payments" (60% of requests) or "recs" (recommendations, 40%). At random
times one dependency gets very slow (seconds per call). Right now `Client`
waits as long as it takes, so the slow calls hold every worker and requests
to the HEALTHY dependency fail too: a cascading failure.

Do the stages in order, in this file:

  Stage 1  Timeouts: give up on a call after TIMEOUT seconds.
  Stage 2  Bulkhead: at most BULKHEAD_LIMIT calls in flight per dependency;
           beyond that, fail at once, so one dependency cannot take every worker.
  Stage 3  Circuit breaker: after a few failures in a row, stop calling the
           dependency for a while (fail fast), then let one probe through.

Check yourself:  uv run pytest labs/circuit_breaker
Peek at a solution (after trying!):  labs/circuit_breaker/reference.py
"""

from __future__ import annotations

import asyncio
import random

from core.services import ServiceError
from core.vtime import now

TIMEOUT = 1.0  # seconds a call may take (the dependencies promise 1 s)
BULKHEAD_LIMIT = 10  # calls in flight per dependency
FAILURES = 5  # failures in a row that open the breaker
COOLDOWN = 5.0  # seconds the breaker stays open before a probe


class Client:
    """Calls one dependency for one user request.

    Contract:
      - `await client.call(dep)` with dep "payments" or "recs" returns what the
        dependency returns.
      - When the call fails, times out or is refused, raise `ServiceError`.
        Never catch other exceptions: they are bugs and must surface.
      - `self.deps[dep]` is the dependency: `await self.deps[dep].call(payload)`.

    The service makes one Client and shares it between all requests, so state you
    keep on `self` (bulkheads, breakers) is shared too.
    """

    def __init__(self, deps: dict, rng: random.Random | None = None) -> None:
        self.deps = deps
        self.rng = rng or random.Random(0)
        # Stage 2: one Bulkhead(BULKHEAD_LIMIT) per dependency, e.g. a dict.
        # Stage 3: one CircuitBreaker() per dependency.

    async def call(self, dep: str, payload=None):
        # Stage 1: wrap the call in `async with asyncio.timeout(TIMEOUT):` and turn
        # the TimeoutError into a ServiceError ("raise ServiceError(...) from None").
        #
        # Stage 2: before calling, `if not bulkhead.try_enter(): raise ServiceError`;
        # after the call (success or failure), `bulkhead.leave()` (use try/finally).
        #
        # Stage 3: before calling, `if not breaker.allow(): raise ServiceError`;
        # then `breaker.record_success()` or `breaker.record_failure()`.
        return await self.deps[dep].call(payload)


class Bulkhead:
    """Stage 2. At most `limit` calls in flight; the rest are refused at once.

      try_enter()  if fewer than `limit` are in flight, count one more and return
                   True; otherwise return False (do not wait)
      leave()      one call finished
    """

    def __init__(self, limit: int = BULKHEAD_LIMIT) -> None:
        self.limit = limit
        self.in_flight = 0

    def try_enter(self) -> bool:
        raise NotImplementedError("TODO stage 2: Bulkhead.try_enter")

    def leave(self) -> None:
        raise NotImplementedError("TODO stage 2: Bulkhead.leave")


class CircuitBreaker:
    """Stage 3. Stops calling a dependency that keeps failing.

    States:
      "closed"     calls go through; `failures` failures in a row open it
      "open"       calls are refused at once, until `cooldown` seconds have passed
      "half-open"  one probe call goes through: success closes it, failure opens
                   it again (for another cooldown)

      allow()           may this call go through? (closed: yes; open: no, unless the
                        cooldown is over: then become half-open and let ONE through)
      record_success()  the call worked
      record_failure()  the call failed or timed out

    Use `now()` (the simulation's clock) for time.
    """

    def __init__(self, failures: int = FAILURES, cooldown: float = COOLDOWN) -> None:
        self.failures = failures
        self.cooldown = cooldown
        self.state = "closed"
        self.failed = 0
        self.opened_at = 0.0

    def allow(self) -> bool:
        raise NotImplementedError("TODO stage 3: CircuitBreaker.allow")

    def record_success(self) -> None:
        raise NotImplementedError("TODO stage 3: CircuitBreaker.record_success")

    def record_failure(self) -> None:
        raise NotImplementedError("TODO stage 3: CircuitBreaker.record_failure")


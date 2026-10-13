"""Lab retry_storm: YOUR FILE. Edit it and save; the live window reruns it.

Users send ~100 requests/s through `Client` to a service. At random times the
service goes down (every call fails) or fails part of its calls. Right now
`Client` makes one call and gives up, so those requests fail.

Do the stages in order, in this file:

  Stage 1  Retry: retry failed calls in `Client.call`.
  Stage 2  Backoff: sleep `backoff_delay(attempt)` between retries, and make it
           exponential: min(cap, base * 2**attempt).
  Stage 3  Jitter: make `backoff_delay` random between 0 and that backoff (full
           jitter), so users do not all come back at the same moment.
  Stage 4  Retry budget: spend a `RetryBudget` token on every retry, so
           retries add at most ~10% load however long the outage.

Check yourself:  uv run pytest labs/retry_storm
Peek at a solution (after trying!):  labs/retry_storm/reference.py
"""

from __future__ import annotations

import asyncio
import random

from core.services import ServiceError

MAX_RETRIES = 3


class Client:
    """Calls the service for one user request.

    Contract:
      - `await client.call(payload)` returns what the service returns.
      - Only `ServiceError` means "the call failed, you may retry".
        Never catch other exceptions: they are bugs and must surface.
      - When it gives up, it re-raises the last `ServiceError`.

    The scenario makes one Client and shares it between all users, so state
    you keep on `self` (like a retry budget) is shared too.
    """

    def __init__(self, service, rng: random.Random | None = None) -> None:
        self.service = service
        self.rng = rng or random.Random(0)
        # Stage 4: keep one RetryBudget here and share it between requests.

    async def call(self, payload=None):
        # Stage 1: retry ServiceError up to MAX_RETRIES times, then re-raise the
        # last error. Hint: a `for attempt in range(MAX_RETRIES + 1):` loop.
        #
        # Stage 2: between tries, await asyncio.sleep(backoff_delay(attempt, rng=self.rng)).
        #
        # Stage 4: once per request call self.budget.deposit(). Before each
        # retry, first check the retry count, then self.budget.try_withdraw();
        # if it says no, re-raise.
        return await self.service.call(payload)


def backoff_delay(attempt: int, base: float = 0.1, cap: float = 5.0,
                  rng: random.Random | None = None) -> float:
    """Seconds to wait before retry number `attempt` (1 for the first retry).

    Stage 2 (backoff): min(cap, base * 2**attempt), so each retry waits twice as long.
    Cap the exponent too (e.g. min(attempt, 32)) so a huge attempt number
    cannot overflow.
    Stage 3 (full jitter): a uniform random number between 0 and that backoff.
    Use `rng` (a random.Random) when given, so runs repeat.

    >>> 0 <= backoff_delay(1, rng=random.Random(1)) <= 0.2
    True
    """
    raise NotImplementedError("TODO stage 2: backoff_delay (exponential backoff)")


class RetryBudget:
    """Stage 4. Retries may add at most `ratio` extra load (0.1 = 10%).

    Every request deposits `ratio` tokens (`deposit()`); every retry costs one
    token (`try_withdraw()`). Tokens never go above `max_tokens`, and the
    budget starts full.

      deposit()       add `ratio` tokens, up to `max_tokens`
      try_withdraw()  if at least one token is left, take it and return True;
                      otherwise return False (do not retry)
    """

    def __init__(self, ratio: float = 0.1, max_tokens: float = 10) -> None:
        self.ratio = ratio
        self.max_tokens = max_tokens
        self.tokens = float(max_tokens)

    def deposit(self) -> None:
        raise NotImplementedError("TODO stage 4: RetryBudget.deposit")

    def try_withdraw(self) -> bool:
        raise NotImplementedError("TODO stage 4: RetryBudget.try_withdraw")

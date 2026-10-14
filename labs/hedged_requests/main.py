"""Lab hedged_requests: YOUR FILE. Edit it and save; the live window reruns it.

Users send ~100 reads/s through your `Client`. Every key is on 3 replicas, and
any one of them can answer. Replies take ~10 ms, but about 1 in 50 takes
100-400 ms (a GC pause, a cache miss, a slow disk): that rare slow reply is
what the p99 user sees. At random times one replica gets much slower for a
while (a compaction, a noisy neighbour, a degraded volume), or every replica
does. Right now `Client` asks one replica and waits as long as it takes.

Do the stages in order, in this file:

  Stage 1  Hedge: if the first replica has not answered after HEDGE_AFTER
           seconds (about the p95 of a reply), send a copy of the read to
           another replica and return whichever answers first.
  Stage 2  Budget and cancel: spend a `HedgeBudget` token on every copy, so
           copies add at most ~5% load however slow things get, and cancel
           the call that lost the race (nobody needs its answer).

Check yourself:  uv run pytest labs/hedged_requests
Peek at a solution (after trying!):  labs/hedged_requests/reference.py
"""

from __future__ import annotations

import asyncio
import random

HEDGE_AFTER = 0.020  # seconds without an answer before sending a copy (~p95 of a reply)


class Client:
    """Reads one key for one user request, from any of the replicas.

    Contract:
      - `await client.read(key)` returns the value a replica returns.
      - `self.replicas` is the list of replicas; `await replica.get(key)` asks one.
        Every replica has every key, so any answer is the right one.
      - Ask each replica at most once per read.

    The scenario makes one Client and shares it between all users, so state you
    keep on `self` (like a hedge budget) is shared too.
    """

    def __init__(self, replicas: list, rng: random.Random | None = None) -> None:
        self.replicas = replicas
        self.rng = rng or random.Random(0)
        # Stage 2: keep one HedgeBudget here and share it between reads.

    async def read(self, key):
        # Stage 1: pick two different replicas (`self.rng.sample(self.replicas, 2)`).
        # Start the first call as a task (`asyncio.ensure_future(first.get(key))`)
        # and wait for it, at most HEDGE_AFTER:
        #     done, _ = await asyncio.wait(calls, timeout=HEDGE_AFTER)
        # If it is not done, start the copy on the second replica, then wait for
        # whichever finishes first:
        #     done, _ = await asyncio.wait(calls, return_when=asyncio.FIRST_COMPLETED)
        # and return `done.pop().result()`.
        #
        # Stage 2: once per read call self.budget.deposit(); send the copy only if
        # self.budget.try_withdraw() says yes (otherwise just keep waiting for the
        # first). Before returning, cancel every call still running (`task.cancel()`):
        # put that in a `finally:`, so it also happens when the user gives up.
        replica = self.rng.choice(self.replicas)
        return await replica.get(key)


class HedgeBudget:
    """Stage 2. Copies may add at most `ratio` extra load (0.05 = 5%).

    Every read deposits `ratio` tokens (`deposit()`); every copy costs one
    token (`try_withdraw()`). Tokens never go above `max_tokens`, and the
    budget starts full.

      deposit()       add `ratio` tokens, up to `max_tokens`
      try_withdraw()  if at least one token is left, take it and return True;
                      otherwise return False (do not send the copy)
    """

    def __init__(self, ratio: float = 0.05, max_tokens: float = 10) -> None:
        self.ratio = ratio
        self.max_tokens = max_tokens
        self.tokens = float(max_tokens)

    def deposit(self) -> None:
        raise NotImplementedError("TODO stage 2: HedgeBudget.deposit")

    def try_withdraw(self) -> bool:
        raise NotImplementedError("TODO stage 2: HedgeBudget.try_withdraw")

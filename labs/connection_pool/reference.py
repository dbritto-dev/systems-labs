"""Lab connection_pool: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio
from collections import deque


class PoolTimeout(Exception):
    """No connection came free within the pool's timeout."""


class Pool:
    def __init__(self, db, max_size: int = 20, timeout: float = 0.5) -> None:
        self.db = db
        self.max_size = max_size
        self.timeout = timeout
        self.idle: list = []  # open connections nobody is using
        self.size = 0  # open connections, idle or in use
        self.waiters: deque[asyncio.Future] = deque()  # requests waiting for a connection, oldest first

    async def acquire(self):
        if self.idle:
            return self.idle.pop()
        if self.size < self.max_size:
            self.size += 1
            try:
                return await self.db.connect()
            except BaseException:
                self.size -= 1
                raise
        fut = asyncio.get_running_loop().create_future()
        self.waiters.append(fut)
        try:
            async with asyncio.timeout(self.timeout):
                return await fut
        except TimeoutError:
            if fut.done() and not fut.cancelled():  # handed a connection just as time ran out
                return fut.result()
            raise PoolTimeout(f"no connection free after {self.timeout:.1f} s") from None

    def release(self, conn) -> None:
        while self.waiters:  # hand it straight to the oldest request still waiting
            fut = self.waiters.popleft()
            if not fut.done():
                fut.set_result(conn)
                return
        self.idle.append(conn)

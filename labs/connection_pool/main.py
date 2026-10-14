"""Lab connection_pool: YOUR FILE. Edit it and save; the live window reruns it.

Users send ~100 requests/s. Each request asks your `Pool` for a database connection
(`acquire()`), runs one query on it, and gives it back (`release()`). Opening a
connection is slow (~40 ms) and a query is fast (~8 ms). The database allows at most
50 open connections and slows down when more than ~20 work at once. Right now every
request opens a brand new connection and closes it afterwards.

Do the stages in order, in this file:

  Stage 1  Reuse: keep released connections in the pool and hand them out again.
  Stage 2  Bound: never open more than `max_size` connections; when all are busy,
           wait until one is released.
  Stage 3  Timeout: wait at most `timeout` seconds for a connection, then raise
           PoolTimeout (fail fast instead of piling up).

Check yourself:  uv run pytest labs/connection_pool
Peek at a solution (after trying!):  labs/connection_pool/reference.py
"""

from __future__ import annotations

import asyncio
from collections import deque


class PoolTimeout(Exception):
    """Stage 3. Raised by acquire() when no connection frees up within `timeout` seconds."""


class Pool:
    """Hands out database connections.

    Contract:
      - `await pool.acquire()` returns an open connection (from `await self.db.connect()`,
        which may raise TooManyConnections when the database already has 50 open).
      - `pool.release(conn)` is called once the request is done with it.
      - `conn.close()` closes a connection (the database can then accept another).

    The scenario makes one Pool for all users, so what you keep on `self` is shared.
    """

    def __init__(self, db, max_size: int = 20, timeout: float = 0.5) -> None:
        self.db = db
        self.max_size = max_size
        self.timeout = timeout
        self.idle: list = []  # Stage 1: open connections nobody is using
        self.size = 0  # Stage 2: open connections, idle or in use
        self.waiters: deque[asyncio.Future] = deque()  # Stage 2: requests waiting, oldest first

    async def acquire(self):
        # Stage 1: if there is an idle connection, hand it out instead of connecting.
        #
        # Stage 2: only connect while self.size < self.max_size (count it in self.size);
        # otherwise wait for a release: `return await self._wait_for_release()`.
        return await self.db.connect()

    def release(self, conn) -> None:
        # Stage 1: keep the connection (self.idle.append(conn)) instead of closing it.
        #
        # Stage 2: if a request is waiting, hand the connection straight to the oldest
        # one (fut.set_result(conn)) instead of putting it back in self.idle.
        conn.close()

    async def _wait_for_release(self):
        """Wait until release() hands this request a connection, and return it.

        Stage 2: make a future (asyncio.get_running_loop().create_future()), append it
        to self.waiters, and await it.
        Stage 3: wait at most self.timeout seconds (async with asyncio.timeout(...)),
        then raise PoolTimeout. Careful: if the future got a connection just as time ran
        out (fut.done() and not fut.cancelled()), return fut.result() instead of losing it.
        """
        raise NotImplementedError("TODO stage 2: wait for a released connection")

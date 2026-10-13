"""Small in-process stand-ins for the things a lab's code calls.

Every service records frozen `Event`s. All services share the
`current_request` context variable: the scenario sets it once per user
request, and every call made while serving that request (including retries in
your code) is tagged with it. Your code never has to pass ids around.
"""

from __future__ import annotations

import asyncio
import random
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable

from core.vtime import now

current_request: ContextVar[int | None] = ContextVar("current_request", default=None)


class ServiceError(Exception):
    """A downstream call failed (the service is down or returned an error)."""


class DatabaseBusy(Exception):
    """The database's queue is full, so the read was rejected."""


@dataclass(frozen=True, slots=True)
class Event:
    t: float
    request: int | None
    attempt: int
    kind: str
    service: str
    key: Any = None
    detail: float = 0.0


class FaultyService:
    """A downstream service that can be down, slow, or fail some calls.

    `attempt` is counted per request: the first call a request makes is
    attempt 0, its first retry attempt 1, and so on.
    """

    def __init__(
        self,
        name: str = "our service",
        latency: float = 0.010,
        error_rate: float = 0.0,
        down_latency: float = 0.002,
        rng: random.Random | None = None,
    ) -> None:
        self.name = name
        self.latency = latency
        self.error_rate = error_rate
        self.down_latency = down_latency
        self.down = False
        self.rng = rng or random.Random(0)
        self.events: list[Event] = []
        self._attempts: dict[int | None, int] = {}

    def set_down(self, down: bool) -> None:
        self.down = down

    def set_slow(self, latency: float) -> None:
        self.latency = latency

    def set_error_rate(self, rate: float) -> None:
        self.error_rate = rate

    def forget(self, request: int | None) -> int:
        """Drop a finished request's attempt count (so endless runs stay small); returns it."""
        return self._attempts.pop(request, 0)

    def _record(self, request: int | None, attempt: int, kind: str, detail: float = 0.0) -> None:
        self.events.append(Event(now(), request, attempt, kind, self.name, None, detail))

    async def call(self, payload: Any = None) -> Any:
        request = current_request.get()
        attempt = self._attempts.get(request, 0)
        self._attempts[request] = attempt + 1
        self._record(request, attempt, "call")
        if self.down:
            await asyncio.sleep(self.down_latency)
            self._record(request, attempt, "error")
            raise ServiceError(f"{self.name} is down")
        await asyncio.sleep(self.latency * (0.6 + 0.8 * self.rng.random()))
        if self.down or (self.error_rate and self.rng.random() < self.error_rate):
            self._record(request, attempt, "error")
            raise ServiceError(f"{self.name} failed")
        self._record(request, attempt, "ok")
        return payload if payload is not None else "ok"


class SlowDatabase:
    """A key/value store: `service_time` per read, `concurrency` reads at a time.

    Reads beyond the concurrency limit wait in a FIFO queue. If `queue_limit`
    is set and the queue is full, the read fails with `DatabaseBusy`.
    `cost(key)` (default 1) multiplies the service time of expensive keys.
    """

    def __init__(
        self,
        data: dict[Any, Any] | None = None,
        service_time: float = 0.020,
        concurrency: int = 8,
        queue_limit: int | None = None,
        name: str = "database",
        cost: Callable[[Any], float] | None = None,
    ) -> None:
        self.data = data if data is not None else {}
        self.cost = cost
        self.service_time = service_time
        self.concurrency = concurrency
        self.queue_limit = queue_limit
        self.name = name
        self.in_flight = 0
        self.queued = 0
        self.reads = 0
        self.events: list[Event] = []
        self._sem: asyncio.Semaphore | None = None

    def _record(self, request: int | None, kind: str, key: Any) -> None:
        self.events.append(
            Event(now(), request, 0, kind, self.name, key, float(self.queued + self.in_flight))
        )

    async def read(self, key: Any) -> Any:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.concurrency)
        request = current_request.get()
        busy = self.in_flight >= self.concurrency
        if self.queue_limit is not None and busy and self.queued >= self.queue_limit:
            self._record(request, "reject", key)
            raise DatabaseBusy(f"{self.name} queue is full")
        self.reads += 1
        self.queued += 1
        self._record(request, "queued", key)
        acquired = False
        try:
            await self._sem.acquire()
            acquired = True
            self.queued -= 1
            self.in_flight += 1
            self._record(request, "start", key)
            try:
                await asyncio.sleep(self.service_time * (self.cost(key) if self.cost else 1.0))
            finally:
                self.in_flight -= 1
            self._record(request, "done", key)
            return self.data.get(key, f"value-{key}")
        finally:
            if acquired:
                self._sem.release()
            else:
                self.queued -= 1


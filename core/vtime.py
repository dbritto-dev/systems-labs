"""Virtual-time asyncio.

`run_virtual(coro)` runs a coroutine on an event loop whose clock is fake.
When nothing is ready to run, the loop does not sleep: it jumps the clock
straight to the next timer. A minute of traffic runs in well under a second,
and the same program always produces the same timeline.

`asyncio.sleep`, `asyncio.timeout`, `asyncio.wait_for`, `loop.call_later` and
`loop.call_at` all work, because they all read `loop.time()`.
"""

from __future__ import annotations

import asyncio
import selectors
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


class _VirtualSelector:
    """Wraps a real selector. `select(timeout)` advances the clock instead of waiting."""

    def __init__(self, real: selectors.BaseSelector) -> None:
        self._real = real
        self.loop: VirtualClockLoop | None = None

    def select(self, timeout: float | None = None):
        ready = self._real.select(0)
        if ready:
            return ready
        loop = self.loop
        assert loop is not None
        if timeout is None:
            raise RuntimeError(
                "virtual clock: nothing is scheduled, so this program would wait forever"
            )
        if timeout > 0:
            target = loop._now + timeout
            scheduled = loop._scheduled  # the loop's timer heap
            if scheduled:
                # Land exactly on the next timer, so float rounding never
                # leaves it a hair in the future.
                when = scheduled[0].when()
                if when <= target + 1e-9:
                    target = when
            loop._now = max(loop._now, target)
        return []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class VirtualClockLoop(asyncio.SelectorEventLoop):
    """A selector event loop with a virtual `time()` that jumps to the next timer."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)
        selector = _VirtualSelector(selectors.DefaultSelector())
        super().__init__(selector)  # type: ignore[arg-type]
        selector.loop = self

    def time(self) -> float:
        return self._now


def run_virtual(coro: Coroutine[Any, Any, T], start: float = 0.0) -> T:
    """Run `coro` to completion on virtual time and return its result."""
    loop = VirtualClockLoop(start)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()


def now() -> float:
    """The running loop's clock (virtual inside `run_virtual`)."""
    return asyncio.get_running_loop().time()


class VirtualRun:
    """A virtual-time loop you can step forward, for simulations that never end.

        sim = VirtualRun()
        sim.spawn(traffic())          # runs in the background, forever
        sim.run_until(60.0)           # the clock is now exactly 60.0
        sim.run_until(120.0)          # ...and the same simulation goes on
        sim.close()
    """

    def __init__(self, start: float = 0.0) -> None:
        self.loop = VirtualClockLoop(start)
        self._tasks: list[asyncio.Task] = []

    @property
    def now(self) -> float:
        return self.loop.time()

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
        task = self.loop.create_task(coro)
        self._tasks.append(task)
        return task

    def run_until(self, t: float) -> None:
        """Advance the clock to t, running everything due on the way.

        Raises the error of any spawned task that failed.
        """
        self.loop.run_until_complete(asyncio.sleep(max(0.0, t - self.loop.time())))
        for task in self._tasks:
            if task.done() and not task.cancelled() and task.exception() is not None:
                raise task.exception()

    def close(self) -> None:
        if self.loop.is_closed():
            return
        try:
            pending = [t for t in asyncio.all_tasks(self.loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
        finally:
            self.loop.close()

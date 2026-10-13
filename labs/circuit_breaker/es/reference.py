"""Laboratorio circuit_breaker: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import asyncio
import random

from core.services import ServiceError
from core.vtime import now

TIMEOUT = 1.0
BULKHEAD_LIMIT = 10
FAILURES = 5
COOLDOWN = 5.0


class Client:
    def __init__(self, deps: dict, rng: random.Random | None = None) -> None:
        self.deps = deps
        self.rng = rng or random.Random(0)
        self.bulkheads = {name: Bulkhead(BULKHEAD_LIMIT) for name in deps}
        self.breakers = {name: CircuitBreaker() for name in deps}

    async def call(self, dep: str, payload=None):
        breaker, bulkhead = self.breakers[dep], self.bulkheads[dep]
        if not breaker.allow():
            raise ServiceError(f"{dep}: circuito abierto")
        if not bulkhead.try_enter():
            raise ServiceError(f"{dep}: bulkhead lleno")
        try:
            async with asyncio.timeout(TIMEOUT):
                result = await self.deps[dep].call(payload)
        except TimeoutError:
            breaker.record_failure()
            raise ServiceError(f"{dep}: tiempo agotado") from None
        except ServiceError:
            breaker.record_failure()
            raise
        finally:
            bulkhead.leave()
        breaker.record_success()
        return result


class Bulkhead:
    def __init__(self, limit: int = BULKHEAD_LIMIT) -> None:
        self.limit = limit
        self.in_flight = 0

    def try_enter(self) -> bool:
        if self.in_flight >= self.limit:
            return False
        self.in_flight += 1
        return True

    def leave(self) -> None:
        self.in_flight -= 1


class CircuitBreaker:
    def __init__(self, failures: int = FAILURES, cooldown: float = COOLDOWN) -> None:
        self.failures = failures
        self.cooldown = cooldown
        self.state = "closed"
        self.failed = 0
        self.opened_at = 0.0

    def allow(self) -> bool:
        match self.state:
            case "closed":
                return True
            case "open" if now() - self.opened_at >= self.cooldown:
                self.state = "half-open"  # deja pasar esta como prueba
                return True
            case _:
                return False  # abierto, o ya hay una prueba en curso

    def record_success(self) -> None:
        self.state, self.failed = "closed", 0

    def record_failure(self) -> None:
        self.failed += 1
        if self.state == "half-open" or self.failed >= self.failures:
            self.state, self.opened_at = "open", now()

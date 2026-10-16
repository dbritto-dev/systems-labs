"""Laboratorio deadlock_avoidance: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import asyncio
import random

from labs.deadlock_avoidance.api import LockTimeout

LOCK_TIMEOUT = 2.0  # una red de seguridad: con un solo orden nada espera tanto, salvo que algo se rompa
MAX_TRIES = 3  # intentos por transferencia, el primero incluido
BASE = 0.01  # segundos; la espera más larga tras el primer timeout
CAP = 0.2  # segundos; ninguna espera dura más que esto


def backoff(attempt: int, rng: random.Random) -> float:
    # Full jitter: dos transferencias que chocaron vuelven en momentos distintos.
    return rng.uniform(0, min(CAP, BASE * 2 ** min(attempt, 30)))


def lock_order(accounts) -> list[int]:
    # Un solo orden global para cada bloqueo que tome cualquiera: un ciclo exigiría que alguien
    # esperara un id menor reteniendo uno mayor, y nadie lo hace.
    return sorted(set(accounts))


class Payments:
    def __init__(self, locks, ledger, audit, rng: random.Random | None = None) -> None:
        self.locks = locks
        self.ledger = ledger
        self.audit = audit
        self.rng = rng or random.Random(0)

    async def lock_all(self, accounts) -> None:
        for attempt in range(1, MAX_TRIES + 1):
            try:
                for account in accounts:
                    await self.locks.acquire(account, timeout=LOCK_TIMEOUT)
                return
            except LockTimeout:
                self.locks.release_all()  # nunca esperes (ni hagas backoff) reteniendo un bloqueo
                if attempt == MAX_TRIES:
                    raise
                await asyncio.sleep(backoff(attempt, self.rng))

    async def transfer(self, src: int, dst: int, amount: int) -> None:
        await self.lock_all(lock_order([src, dst]))
        try:
            await self.ledger.move(src, dst, amount)  # la sección crítica: solo el libro contable
        finally:
            self.locks.release_all()
        await self.audit.record([(src, -amount), (dst, amount)])  # trabajo lento, tras los bloqueos

    async def settle(self, entries) -> None:
        await self.lock_all(lock_order(account for account, _ in entries))  # todas, al principio
        try:
            await self.ledger.apply(entries)
        finally:
            self.locks.release_all()
        await self.audit.record(entries)

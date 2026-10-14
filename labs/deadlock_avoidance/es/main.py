"""Laboratorio deadlock_avoidance: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Un servicio de pagos mueve dinero entre cuentas. Cada transferencia bloquea las dos cuentas
(bloqueos de fila en el libro contable), mueve el dinero, escribe el registro de auditoría y libera
los bloqueos. Ahora mismo bloquea en el orden de la petición: primero `src`, luego `dst`. Cuando A le
paga a B mientras B le paga a A, cada una retiene un bloqueo y espera el de la otra, para siempre:
un interbloqueo. Luego cada transferencia que toca A o B espera detrás de ellas, reteniendo su propio
primer bloqueo, y la pila crece hasta que el servicio se queda sin conexiones y se congela. Nadie lo
rompe hasta que el servidor mata las transacciones (8 s después).

Haz las etapas en orden, en este archivo:

  Etapa 1  Timeouts de bloqueo con reintento: en `lock_all`, pide cada bloqueo con
           `timeout=LOCK_TIMEOUT` (0,05 s). Ante LockTimeout, `release_all()` (nunca esperes
           reteniendo un bloqueo), duerme `backoff(attempt, rng)` y vuelve a intentarlo, hasta
           MAX_TRIES (8) intentos; tras el último, lanza el error. Se acabaron los congelamientos,
           pero cada interbloqueo (y cada espera larga en una cuenta muy usada) cuesta ahora
           timeouts, reintentos y latencia. Sin jitter, dos transferencias que chocaron reintentan a
           la vez y vuelven a chocar (un bloqueo activo, livelock en inglés).
  Etapa 2  Un orden global de bloqueo: en `lock_order`, ordena las cuentas por id y bloquéalas en
           ese orden, en `transfer` y en `settle` (el proceso por lotes: todas sus cuentas, en orden,
           antes de mover nada). Un ciclo exige que alguien espere un id menor reteniendo uno mayor:
           nadie lo hace, así que no hay ningún interbloqueo. Deja un LOCK_TIMEOUT largo (2 s) y
           MAX_TRIES = 3 solo como red de seguridad, y mantén corta la sección crítica: escribe la
           auditoría DESPUÉS de liberar los bloqueos, para que una escritura lenta no frene a nadie.

Lo que tienes (mira labs/deadlock_avoidance/api.py):
  await self.locks.acquire(account, timeout=None)   lanza LockTimeout tras `timeout` segundos
  self.locks.release(account)    self.locks.release_all()    self.locks.holding()
  await self.ledger.move(src, dst, amount)          await self.ledger.apply(entries)
  await self.audit.record(entries)                  2-6 ms por fila; a veces se atasca
  self.rng (un random.Random) para el jitter

Cuando transfer() o settle() devuelven o lanzan un error, su transacción termina: se liberan todos
los bloqueos que retenga. Lanza LockTimeout para rendirte (el cliente recibe un error).

Compruébalo:  LABS_LANG=es uv run pytest labs/deadlock_avoidance
Mira una solución (¡después de intentarlo!):  labs/deadlock_avoidance/es/reference.py
"""

from __future__ import annotations

import asyncio
import random

from labs.deadlock_avoidance.api import LockTimeout

LOCK_TIMEOUT = None  # segundos que puede durar una espera de bloqueo; None espera siempre. Etapa 1: 0.05. Etapa 2: 2.0
MAX_TRIES = 1  # intentos por transferencia, el primero incluido. Etapa 1: 8. Etapa 2: 3
BASE = 0.01  # etapa 1: segundos; la espera más larga tras el primer timeout
CAP = 0.2  # etapa 1: segundos; ninguna espera dura más que esto


def backoff(attempt: int, rng: random.Random) -> float:
    """Etapa 1. Segundos de espera tras el timeout número `attempt` (1 tras el primero).

    Contrato:
      - Una espera al azar entre 0 y min(CAP, BASE * 2 ** attempt) ("full jitter").
      - Nunca negativa, nunca mayor que CAP, por grande que sea `attempt`.
      - Usa `rng` (no el módulo `random`), para que una ejecución sea siempre igual.
    """
    # Etapa 1: return rng.uniform(0, min(CAP, BASE * 2 ** min(attempt, 30)))
    raise NotImplementedError("TODO etapa 1: backoff(attempt, rng)")


def lock_order(accounts) -> list[int]:
    """Etapa 2. El orden en que bloquear `accounts`: el mismo para cada transferencia y cada lote.

    Contrato:
      - Cada cuenta una vez, por id ascendente: lock_order([9, 4, 9, 2]) == [2, 4, 9].
      - Acepta cualquier iterable (una lista, un generador).
    """
    # Etapa 2: return sorted(set(accounts))
    raise NotImplementedError("TODO etapa 2: lock_order(accounts)")


class Payments:
    """Mueve dinero entre cuentas sin interbloqueos, sin perder dinero y sin congelar el servicio.

    Contrato:
      - `await transfer(src, dst, amount)` mueve `amount` centavos de `src` a `dst`, reteniendo los
        bloqueos de ambas cuentas mientras llama al libro contable. Lanza LockTimeout para rendirte.
      - `await settle(entries)` aplica un lote, [(account, delta)] (los deltas suman 0), reteniendo
        el bloqueo de cada cuenta mientras llama al libro contable.
      - Libera tus bloqueos al terminar (o al abandonar un intento).
    """

    def __init__(self, locks, ledger, audit, rng: random.Random | None = None) -> None:
        self.locks = locks
        self.ledger = ledger
        self.audit = audit
        self.rng = rng or random.Random(0)

    async def lock_all(self, accounts) -> None:
        # Etapa 1: mete esto en un bucle de MAX_TRIES intentos. Ante LockTimeout:
        #          self.locks.release_all(), y si era el último intento, lanza el error; si no,
        #          `await asyncio.sleep(backoff(attempt, self.rng))` y empieza otra vez por la primera.
        for account in accounts:
            await self.locks.acquire(account, timeout=LOCK_TIMEOUT)  # espera siempre si es None

    async def transfer(self, src: int, dst: int, amount: int) -> None:
        # Etapa 2: bloquea `lock_order([src, dst])`, y pasa la auditoría después del finally.
        await self.lock_all([src, dst])  # src primero: B -> A toma B mientras A -> B retiene A
        try:
            await self.ledger.move(src, dst, amount)
            await self.audit.record([(src, -amount), (dst, amount)])  # trabajo lento, con ambos bloqueos
        finally:
            self.locks.release_all()

    async def settle(self, entries) -> None:
        # Etapa 2: bloquea `lock_order(account for account, _ in entries)`, y audita tras el finally.
        await self.lock_all([account for account, _ in entries])  # en el orden del proceso
        try:
            await self.ledger.apply(entries)
            await self.audit.record(entries)
        finally:
            self.locks.release_all()

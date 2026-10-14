"""Laboratorio saga: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import asyncio

from labs.saga.api import StepFailed, Timeout

TRIES = 6  # intentos de un paso que da timeout, con la misma clave, antes de rendirse
UNDO_TRIES = 40  # una compensación tiene que ocurrir: sigue intentándolo (backoff hasta MAX_BACKOFF)
BACKOFF = 0.1  # segundos antes del primer reintento; se duplica cada vez
MAX_BACKOFF = 1.0


class Orchestrator:
    def __init__(self, payments, stock, shipping, log) -> None:
        self.payments = payments
        self.stock = stock
        self.shipping = shipping
        self.log = log
        # Cada paso con su compensación, en orden.
        self.steps = [(payments.charge, payments.refund), (stock.reserve, stock.release),
                      (shipping.book, shipping.cancel)]

    async def place(self, saga_id: str, order) -> bool:
        # Escritura anticipada: el registro conoce la saga antes de que pueda ocurrir el primer paso.
        state = {"order": order, "status": "running"}
        await self.log.save(saga_id, state)
        return await self.resume(saga_id, state)

    async def recover(self) -> None:
        # Un orquestador nuevo tras una caída: termina cada saga que el registro dice sin terminar.
        sagas = await self.log.items()
        await asyncio.gather(*(self.resume(saga_id, state) for saga_id, state in sagas),
                             return_exceptions=True)

    async def resume(self, saga_id: str, state: dict) -> bool:
        """Ejecuta una saga desde su estado guardado: hacia delante si está en marcha, si no, compensa."""
        order = state["order"]
        if state["status"] == "running":
            refs = []
            try:
                for do, _ in self.steps:
                    # Siempre la misma clave: un paso que ya ocurrió devuelve su primera ref.
                    refs.append(await self.attempt(do, order, key=saga_id))
                await self.log.delete(saga_id)
                return True
            except StepFailed:
                pass  # un no, o sin respuesta tras todos los intentos: deshazlo
            # Dilo antes de deshacer nada, para que una caída desde aquí siga compensando.
            await self.log.save(saga_id, {"order": order, "status": "compensating"})
        await self.compensate(saga_id, [None] * len(self.steps))
        await self.log.delete(saga_id)
        return False

    async def compensate(self, saga_id: str, refs: list) -> None:
        """Deshaz los pasos, del último al primero, por clave: deshacer lo que nunca pasó no hace
        nada, así que también se deshace un paso que dio timeout (y quizá ocurrió)."""
        for (_, undo), ref in reversed(list(zip(self.steps, refs))):
            await self.attempt(undo, ref, key=saga_id, tries=UNDO_TRIES)

    async def attempt(self, call, *args, tries: int = TRIES, **kwargs):
        """Llama a un paso o a una compensación, y reintenta los timeouts con backoff (es seguro:
        lleva clave)."""
        for n in range(tries):
            try:
                return await call(*args, **kwargs)
            except Timeout:
                if n == tries - 1:
                    raise
                await asyncio.sleep(min(MAX_BACKOFF, BACKOFF * 2 ** n))

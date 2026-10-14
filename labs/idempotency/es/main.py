"""Laboratorio idempotency: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Los clientes pagan a través de `PaymentService.charge(key, account, amount)`. Cada pago lleva
una clave de idempotencia. Cuando una respuesta se pierde o tarda, el cliente reintenta con
la MISMA clave. Ahora mismo cada intento vuelve a cobrar la tarjeta: un pago reintentado se
cobra dos veces.

Haz las etapas en orden, en este archivo:

  Etapa 1  Recordar respuestas: después de cobrar, guarda el recibo bajo la clave; cuando la
           clave vuelva, devuelve el recibo guardado en vez de cobrar.
  Etapa 2  Reservar la clave antes: un reintento puede llegar mientras el primer intento
           sigue cobrando. Reclama la clave de forma atómica (`store.add`, como SET NX de
           Redis) antes de cobrar; un duplicado que la encuentra en curso espera el recibo
           (o lanza Conflict). Guárdalo todo con caducidad (ttl) para que el almacén no
           crezca para siempre.

Lo que tienes (mira labs/idempotency/api.py):
  await self.ledger.insert(account, amount) -> charge_id     cada llamada es un cobro nuevo
  await self.store.get(key) / .set(key, value, ttl) / .add(key, value, ttl) -> bool
  IN_PROGRESS, Conflict

Compruébalo:  LABS_LANG=es uv run pytest labs/idempotency
Mira una solución (¡después de intentarlo!):  labs/idempotency/es/reference.py
"""

from __future__ import annotations

import asyncio

from labs.idempotency.api import IN_PROGRESS, Conflict

TTL = 300.0  # segundos que se recuerda una clave


class PaymentService:
    """Cobra una tarjeta una sola vez por clave de idempotencia.

    Contrato:
      - `await service.charge(key, account, amount)` devuelve un recibo:
        {"charge_id": <int>, "amount": <amount>}.
      - La misma clave nunca debe cobrarse dos veces, y cada intento de la misma clave
        debería recibir el mismo recibo.
      - Lanza `Conflict(key)` si aún no puedes responder (el cliente reintenta un poco después).
    """

    def __init__(self, ledger, store) -> None:
        self.ledger = ledger
        self.store = store

    async def charge(self, key: str, account: int, amount: int) -> dict:
        # Etapa 1: primero `seen = await self.store.get(key)`; si hay un recibo, devuélvelo.
        #          Después de cobrar, `await self.store.set(key, receipt, TTL)`.
        # Etapa 2: reclama la clave antes de cobrar: `if await self.store.add(key, IN_PROGRESS, TTL):`
        #          cobra y guarda el recibo; si no, espera (consulta `get` cada ~50 ms, hasta
        #          ~2 s) a que el valor sea un recibo, y lanza Conflict(key) si nunca lo es.
        charge_id = await self.ledger.insert(account, amount)
        return {"charge_id": charge_id, "amount": amount}

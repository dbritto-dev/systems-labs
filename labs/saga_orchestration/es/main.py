"""Laboratorio saga_orchestration: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Un pedido pasa por tres servicios, y no hay ninguna transacción que los abarque. Tu
`Orchestrator` ejecuta una saga por pedido: cobrar la tarjeta (payments), reservar los
artículos (stock), reservar un mensajero (shipping). Ahora mismo solo los llama en orden:
cuando un paso falla a mitad, los pasos anteriores se quedan hechos. Al cliente se le cobra
un pedido que nunca sale, y los artículos se quedan reservados para nadie.

Haz las etapas en orden, en este archivo:

  Etapa 1  Compensar: cuando un paso falla, deshaz los pasos que salieron bien, del último al
           primero (libera el inventario, luego reembolsa la tarjeta), y devuelve False.
  Etapa 2  Sagas idempotentes y reanudables. Un paso puede dar timeout y aun así haberse
           hecho, y el propio orquestador puede caerse a mitad (un despliegue, falta de memoria).
           - Pasa key=saga_id a cada paso y a cada compensación: así un reintento nunca cobra
             dos veces, y puedes deshacer un paso cuya respuesta nunca recibiste.
           - Reintenta los timeouts con backoff (`attempt`); sigue reintentando las compensaciones.
           - Guarda el estado de la saga en `self.log` antes de cada fase ("running", luego
             "compensating"), bórralo cuando la saga termine, y en `recover()` termina cada
             saga que el registro aún tenga.

Lo que tienes (mira labs/saga_orchestration/api.py):
  await payments.charge(order, key=None) -> ref      await payments.refund(ref=None, key=None)
  await stock.reserve(order, key=None) -> ref        await stock.release(ref=None, key=None)
  await shipping.book(order, key=None) -> ref        await shipping.cancel(ref=None, key=None)
  Declined (un no definitivo), Timeout (sin respuesta: pudo hacerse); los dos son StepFailed
  await log.save(saga_id, state) / log.delete(saga_id) / log.items() -> [(saga_id, state)]

Compruébalo:  LABS_LANG=es uv run pytest labs/saga_orchestration
Mira una solución (¡después de intentarlo!):  labs/saga_orchestration/es/reference.py
"""

from __future__ import annotations

import asyncio

from labs.saga_orchestration.api import StepFailed, Timeout

TRIES = 6  # intentos de un paso que da timeout, con la misma clave, antes de rendirse
UNDO_TRIES = 40  # una compensación tiene que ocurrir: sigue intentándolo (backoff hasta MAX_BACKOFF)
BACKOFF = 0.1  # segundos antes del primer reintento; se duplica cada vez
MAX_BACKOFF = 1.0


class Orchestrator:
    """Ejecuta la saga de cada pedido: cobrar -> reservar -> enviar.

    Contrato:
      - `await orch.place(saga_id, order)` ejecuta una saga nueva. Devuelve True cuando el
        pedido está completo (cobrado, reservado, enviado) y False cuando lo deshiciste. Si
        lanza StepFailed, te rendiste y lo dejaste todo como estaba.
      - `await orch.recover()` se llama una vez en un orquestador NUEVO tras una caída (los
        mismos servicios y el mismo registro; todo lo que tenías en memoria se perdió).
        Termina cada saga que la caída interrumpió, hacia delante o hacia atrás.
      - Nunca captures otras excepciones: son errores y deben salir a la luz.
    """

    def __init__(self, payments, stock, shipping, log) -> None:
        self.payments = payments
        self.stock = stock
        self.shipping = shipping
        self.log = log
        # Cada paso con su compensación, en orden.
        self.steps = [(payments.charge, payments.refund), (stock.reserve, stock.release),
                      (shipping.book, shipping.cancel)]

    async def place(self, saga_id: str, order) -> bool:
        # Etapa 1: guarda en una lista las refs que devuelven los pasos; envuelve los pasos en
        #          `try: ... except StepFailed:` y ahí `await self.compensate(saga_id, refs)`
        #          y devuelve False.
        # Etapa 2: primero `await self.log.save(saga_id, {"order": order, "status": "running"})`,
        #          luego `return await self.resume(saga_id, ese estado)`, y mueve los pasos allí.
        await self.payments.charge(order)
        await self.stock.reserve(order)
        await self.shipping.book(order)
        return True

    async def recover(self) -> None:
        # Etapa 2: `for saga_id, state in await self.log.items():` reanuda cada una, todas a la
        #          vez (`asyncio.gather(..., return_exceptions=True)`).
        return  # no se guardó nada, así que no hay nada que reanudar

    async def resume(self, saga_id: str, state: dict) -> bool:
        """Etapa 2. Ejecuta una saga desde su estado guardado, y bórrala del registro al terminar.

          status "running":       ejecuta cada paso con `self.attempt(do, order, key=saga_id)`;
                                  un paso que ya ocurrió solo devuelve su primera ref. Si uno
                                  falla del todo, guarda status "compensating" y luego compensa.
          status "compensating":  compensa (la caída llegó mientras deshacías: deshazlo todo otra vez).
        Devuelve True si el pedido se completó, False si se deshizo.
        """
        raise NotImplementedError("PENDIENTE etapa 2: Orchestrator.resume")

    async def compensate(self, saga_id: str, refs: list) -> None:
        """Etapa 1. Deshaz los pasos que ocurrieron, del último al primero.

        `refs[i]` es lo que devolvió el paso i. Etapa 1: `await undo(ref)` por cada ref que
        recibiste, en orden inverso (une `self.steps` con `refs` con zip, y luego `reversed`).
        Etapa 2: deshaz cada paso por clave, `await self.attempt(undo, None, key=saga_id,
        tries=UNDO_TRIES)`, incluso el que dio timeout: pudo haber ocurrido, y deshacer lo que
        nunca pasó no hace nada.
        """
        raise NotImplementedError("PENDIENTE etapa 1: Orchestrator.compensate")

    async def attempt(self, call, *args, tries: int = TRIES, **kwargs):
        """Etapa 2. `await call(*args, **kwargs)`; si da Timeout, espera
        min(MAX_BACKOFF, BACKOFF * 2 ** n) y vuelve a intentarlo, hasta `tries` veces, y luego
        lanza la excepción. Reintentar solo es seguro porque la llamada lleva clave. Deja pasar
        Declined enseguida."""
        raise NotImplementedError("PENDIENTE etapa 2: Orchestrator.attempt")

"""Laboratorio graceful_shutdown: una solución que funciona. Léela después de intentar main.py."""

from __future__ import annotations

import asyncio

MARGIN = 1.0  # segundos de holgura sobre el peor caso del balanceador de carga
EXIT_BEFORE_KILL = 5.0  # sal así de antes de SIGKILL, quede lo que quede en curso


async def on_sigterm(server) -> None:
    await shutdown(server)


async def drain(server, deadline: float) -> None:
    """Deja de aceptar trabajo nuevo, deja que termine lo que está en curso (como mucho `deadline` segundos), sal."""
    server.stop_accepting()
    server.close_idle()  # los clientes con conexión persistente se reconectan a otra; los flujos también
    await server.drained(deadline)
    server.exit()


async def shutdown(server) -> None:
    """Primero deja de estar lista, espera a que ningún nodo del balanceador nos mande conexiones nuevas, y drena."""
    server.fail_readiness()
    wait = server.health_interval * server.unhealthy_threshold + server.deregistration_delay + MARGIN
    await asyncio.sleep(wait)  # mientras tanto sigue sirviendo todo lo que llega
    await drain(server, server.grace - wait - EXIT_BEFORE_KILL)

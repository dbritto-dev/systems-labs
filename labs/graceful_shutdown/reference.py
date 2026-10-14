"""Lab graceful_shutdown: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio

MARGIN = 1.0  # seconds of slack on top of the load balancer's worst case
EXIT_BEFORE_KILL = 5.0  # leave this long before the hard kill, whatever is still in flight


async def on_sigterm(server) -> None:
    await shutdown(server)


async def drain(server, deadline: float) -> None:
    """Stop taking new work, let in-flight work finish (for at most `deadline` seconds), exit."""
    server.stop_accepting()
    server.close_idle()  # kept-alive clients reconnect elsewhere; streams too
    await server.drained(deadline)
    server.exit()


async def shutdown(server) -> None:
    """Readiness off first, wait until no balancer node sends us new connections, then drain."""
    server.fail_readiness()
    wait = server.health_interval * server.unhealthy_threshold + server.deregistration_delay + MARGIN
    await asyncio.sleep(wait)  # still serving everything that arrives meanwhile
    await drain(server, server.grace - wait - EXIT_BEFORE_KILL)

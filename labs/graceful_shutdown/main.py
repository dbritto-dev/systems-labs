"""Lab graceful_shutdown: YOUR FILE. Edit it and save; the live window reruns it.

Users send ~300 requests/s to 6 instances of an app behind a load balancer. The balancer
(3 nodes) picks an instance, round robin, when a client opens a connection; 60% of requests
come on connections clients keep open (keep-alive), and users keep ~100 streams open
(WebSockets, server-sent events). Each balancer node checks each instance's readiness
every 2 s and takes it out of rotation after 3 failed checks in a row, plus 1 s to apply it.

Deploys, scale-ins and node drains stop instances: the orchestrator sends SIGTERM, starts
a replacement (it boots in 4 s, and then the next old instance gets SIGTERM), and 30 s
after SIGTERM kills the old one (SIGKILL) whatever it is doing. Your `on_sigterm(server)`
runs when an instance gets SIGTERM. Right now it exits at once: every request and stream
in flight is cut, and for seconds the balancer still sends new connections to an instance
that is gone.

What `server` lets you do (all on the virtual clock: `await asyncio.sleep(s)` works):
  server.fail_readiness()        the readiness check (GET /ready) answers 503 from now on
  server.stop_accepting()        close the listening socket: new connections are refused
  server.close_idle()            close idle kept-alive connections, answer every later
                                 request with "Connection: close", and ask streams to
                                 reconnect (they move to another instance)
  await server.drained(timeout)  wait until nothing is in flight (True) or until `timeout`
                                 seconds have passed (False); None waits for ever
  server.in_flight               requests and streams in flight now
  server.exit()                  the process exits; whatever is in flight is cut
  server.health_interval (2 s), server.unhealthy_threshold (3),
  server.deregistration_delay (1 s), server.grace (30 s, SIGTERM to SIGKILL)

Do the stages in order, in this file:

  Stage 1  Drain: stop accepting, close idle connections, wait for in-flight work (with a
           deadline), then exit.
  Stage 2  Readiness off first: fail the readiness check and keep serving until the
           balancer has taken you out, then drain.

Check yourself:  uv run pytest labs/graceful_shutdown
Peek at a solution (after trying!):  labs/graceful_shutdown/reference.py
"""

from __future__ import annotations

import asyncio  # stage 2: await asyncio.sleep(...)


async def on_sigterm(server) -> None:
    """Runs once, when this instance gets SIGTERM. When it returns, the process exits.

    Contract:
      - It may await (asyncio.sleep, server.drained) for as long as it likes, but at
        `server.grace` seconds (30) after SIGTERM the instance is killed: whatever is still
        in flight then is cut, and on_sigterm is cancelled.
      - The orchestrator does not wait for it: the replacement starts at once.
    """
    # Stage 1: await drain(server, server.grace - 5) instead.
    #
    # Stage 2: await shutdown(server) instead.
    server.exit()


async def drain(server, deadline: float) -> None:
    """Stage 1. Stop taking new work, let the work in flight finish, then exit.

    1. server.stop_accepting(): new connections are refused from now on.
    2. server.close_idle(): clients that keep a connection open would otherwise send
       request after request on it for ever (the listener is closed, not their
       connection), and streams last minutes. This makes them all reconnect elsewhere.
    3. await server.drained(deadline): wait for the requests in flight, at most `deadline`
       seconds (a slow request takes up to 5 s).
    4. server.exit().

    Then watch: nothing is cut any more, but the balancer does not know the listener is
    closed until 3 health checks in a row fail. Until then it still sends 1 new connection
    in 6 to this instance, and each one is refused: errors at the door. And the next old
    instance gets SIGTERM as soon as the new one is ready, before the balancer sends it
    anything: for a few seconds only 4 of 6 instances serve.
    """
    raise NotImplementedError("TODO stage 1: drain")


async def shutdown(server) -> None:
    """Stage 2. Leave the load balancer first, then drain.

    1. server.fail_readiness(): from the next check on, each balancer node counts a failure.
       Keep serving everything that arrives meanwhile (do not stop accepting yet).
    2. Wait until every balancer node has taken the instance out of rotation:
       server.health_interval * server.unhealthy_threshold (the checks) plus
       server.deregistration_delay (the time a node takes to apply it), plus a margin
       of about 1 s. `await asyncio.sleep(...)` (this is the preStop hook's 'sleep').
    3. await drain(server, deadline) with a deadline that ends well before the hard kill:
       server.grace - the time you waited - a few seconds.

    Hint: a wait of exactly interval * threshold is not enough: a node needs its 1 s to
    apply the change, and the checks of each node come at their own moments.
    """
    raise NotImplementedError("TODO stage 2: shutdown")

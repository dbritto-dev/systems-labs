"""Lab load_balancing: YOUR FILE. Edit it and save; the live window reruns it.

Users send ~250 requests/s. Each one reaches one of 4 load balancers, and that balancer
asks your `Balancer.pick()` which of the 8 servers gets it. A server works on 4 requests
at once (~40 ms each) and queues the rest. A request not answered within 1 s times out
(the user gets a 504). Right now every balancer sends requests round robin: server 0,
1, 2, ... 7, 0, 1, ... whatever state the servers are in.

At random times one server turns slow (a noisy neighbour, a GC storm, a failing disk) or
is replaced by a cold one that is slow until it warms up. Round robin still gives it 1 in
8 requests: its queue grows, and its users wait, then time out.

What a balancer knows: `loads`, how many requests each server had in flight (queued or
running) on average over the half second before its last load report. Every balancer
reads a new report every 0.5 s, each at its own moment, so `loads` is up to a second
behind: stale.

Do the stages in order, in this file:

  Stage 1  Least outstanding requests: send each request to the server with the fewest
           requests in flight.
  Stage 2  Power of two choices: pick two servers at random and send the request to the
           less loaded of the two.

Check yourself:  uv run pytest labs/load_balancing
Peek at a solution (after trying!):  labs/load_balancing/reference.py
"""

from __future__ import annotations

import random


class Balancer:
    """Chooses a server for each request, on one load balancer.

    Contract:
      - `pick(loads)` returns the index (0 to servers - 1) of the server for this request.
      - `loads[i]` is how many requests server i had in flight (queued or running), on
        average over the 0.5 s before the last load report (a float, up to a second
        behind). It is a copy: changing it changes nothing.
      - `self.rng` is this balancer's random generator: use it (not `random`), so a run
        is the same every time.

    The scenario makes one Balancer per load balancer (4 of them); they share nothing.
    """

    def __init__(self, servers: int, rng: random.Random) -> None:
        self.servers = servers
        self.rng = rng
        self.next = 0  # round robin: the server for the next request

    def pick(self, loads: list[float]) -> int:
        # Stage 1: return least_outstanding(loads) instead.
        #
        # Stage 2: return two_choices(loads, self.rng) instead.
        server = self.next
        self.next = (self.next + 1) % self.servers
        return server


def least_outstanding(loads: list[float]) -> int:
    """Stage 1. The index of the server with the fewest requests in flight in `loads`.

    On a tie, any of them will do (the first one is fine). Hint: min(range(len(loads)),
    key=...) finds it in one line.

    Then watch: the slow server's queue keeps its share low, but every balancer sends
    ALL its requests for the next half second to the one server that looked idle in its
    report. When that is the slow server, a whole burst lands on it and times out.
    (Breaking ties at random does not help: the loads are averages, so there is almost
    always one smallest.)
    """
    raise NotImplementedError("TODO stage 1: least_outstanding")


def two_choices(loads: list[float], rng: random.Random) -> int:
    """Stage 2. Pick two different servers at random; return the one with fewer requests
    in flight (either one on a tie).

    Hint: rng.sample(range(len(loads)), 2) gives two different indexes.

    Why it beats the least loaded one when reports are stale: the busiest servers are
    still avoided (the busiest one is never chosen), but the requests spread over every
    server that is not busy, instead of all landing on the one that looked best half a
    second ago.
    """
    raise NotImplementedError("TODO stage 2: two_choices")

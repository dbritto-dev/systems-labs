"""Lab replication_lag: YOUR FILE. Edit it and save; the live window reruns it.

A primary database and 4 read replicas (r1..r4). Every write commits on the primary and
reaches each replica 50-200 ms later; sometimes much later (a replica falls behind, restarts,
or a write spike hits). Your `Router` decides where every read goes. Right now it sends each
read to any replica that is up, so users miss their own changes right after making them,
and pages jump back in time when a read lands on a replica that is behind.

Do the stages in order, in this file:

  Stage 1  Read your writes: remember the log position (LSN) of each session's last write,
           and only read from a replica that has applied it; if none has, read the primary.
  Stage 2  Monotonic reads: also remember the newest position each session has already seen,
           so its reads never go back in time. Keep most reads off the primary (at most 35%).

Check yourself:  uv run pytest labs/replication_lag
Peek at a solution (after trying!):  labs/replication_lag/reference.py
"""

from __future__ import annotations

import random


class Router:
    """Decides where each read goes. The scenario calls:

      wrote(session, lsn)               a session's write committed on the primary at log
                                        position `lsn` (positions only grow)
      pick(session, key, replicas)      a read: return "primary" or a replica's name
      saw(session, key, name, lsn)      after a read: node `name` answered, and the value it gave
                                        was written at position `lsn` (its version)

    `replicas` is a list of Replica(name, lsn, up): the position each replica had applied at
    its last report (every 100 ms, so it may be a little old, never ahead), and whether it
    answers at all. Sessions are ints; keys are strings. Use `self.rng` for random choices.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random(0)
        # Stage 1: a dict session -> the LSN of its last write.
        # Stage 2: and, per (session, key), the newest version it has seen.

    def wrote(self, session: int, lsn: int) -> None:
        pass  # Stage 1: remember it

    def pick(self, session: int, key: str, replicas: list) -> str:
        up = [r.name for r in replicas if r.up]
        # Stage 1: keep only replicas whose r.lsn is at least the session's last write.
        # Stage 2: ... and at least the version of this key the session has already seen.
        # If no replica qualifies, return "primary".
        return self.rng.choice(up) if up else "primary"

    def saw(self, session: int, key: str, name: str, lsn: int) -> None:
        pass  # Stage 2: remember the newest version of this key this session has seen

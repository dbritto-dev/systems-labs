"""Lab chain_replication: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "chain_replication",
    "params": {"rate": Param(20.0)},
}

NODES = 4  # replicas in the chain when nothing is wrong
DETECT = 1.0  # the master drops a crashed node after its session times out
EJECT = 2.0  # ... and ejects a slow node after this long (it is fenced: it restarts empty)
COPY = 1.0  # seconds the tail's state takes on the wire to a joining node

BEFORE = 15.0  # stale reads are counted from 15 s before an incident to its end; p99 over those 15 s
AFTER = 5.0  # the node is back at the end of an incident: lost writes and outage are judged until 5 s later
SETTLE = 2.5  # wait this long after a window for the last requests (a client waits 2 s)

STALE_MAX = 0  # reads that missed an acknowledged write
LOST_MAX = 0  # acknowledged writes no live replica holds
OUTAGE_MAX = 3  # seconds in which more than 10% of the writes failed
OUTAGE_SHARE = 0.9  # a second is down when fewer of its writes than this succeeded
P99_MAX = 0.5  # seconds: the write latency p99 before the incident


def stage_of(stale_ok: bool, lost_ok: bool, outage_ok: bool, replicas_ok: bool, p99_ok: bool) -> int:
    """Judge the stage from what the first incident showed: 0 primary-backup (stale reads or lost
    writes), 1 a chain (consistent, but a failure stalls it or the node that joins stays behind),
    2 a chain with repair."""
    if not (stale_ok and lost_ok):
        return 0
    if not (outage_ok and replicas_ok and p99_ok):
        return 1
    return 2

"""Lab paxos_consensus: the numbers and how the stage is judged.

The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "paxos_consensus",
    "params": {"rate": Param(10.0)},
}

NODES = 5
BEFORE = (15.0, 3.0)  # the calm measured before each incident: from 15 s to 3 s before it
AFTER = 5.0  # an incident is judged until this long after it ends
DEADLINE = 2.0  # a command counts as decided in time if its client hears back within this (it gives up then)

LIVE_MIN = 0.95  # share of commands decided within DEADLINE, during the incident and just after it
COST_MAX = 16.0  # messages between nodes per decided command, in the calm


def stage_of(agree_ok: bool, kept_ok: bool, live_ok: bool, cheap_ok: bool) -> int:
    """Judge the stage from what the first incident (and the calm before it) showed:
    0 first proposal wins (nodes disagree), 1 Paxos per slot (safe), 2 Multi-Paxos (safe, live, cheap)."""
    if not (agree_ok and kept_ok):
        return 0
    if not (live_ok and cheap_ok):
        return 1
    return 2

"""Lab replication_lag: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "replication_lag",
    "params": {"rate": Param(200.0)},
}

REPLICAS = 4  # r1..r4; node 0 in the picture is the primary
AFTER = 5.0  # violations are counted until this long after an incident ends (catching up)
PRIMARY_MAX = 0.35  # at most this share of reads may go to the primary


def stage_of(ryw_ok: bool, mono_ok: bool, primary_ok: bool) -> int:
    """Judge the stage from what the first incident showed: 0 any replica (or everything on the
    primary), 1 read your writes, 2 read your writes + monotonic reads."""
    if not (ryw_ok and primary_ok):
        return 0
    if not mono_ok:
        return 1
    return 2

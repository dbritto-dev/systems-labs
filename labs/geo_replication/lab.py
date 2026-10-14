"""Lab geo_replication: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "geo_replication",
    "params": {"rate": Param(200.0)},
}

AFTER = 5.0  # operations this long after an incident are judged with it (users coming back)
READ_P99_MAX = 0.050  # seconds: p99 of a read, in the worst region (users served in their own region)
WRITE_P99_MAX = 0.400  # seconds: p99 of a write, the same way (a write may cross one ocean, not two)
AVAILABLE_MIN = 0.99  # share of operations answered (after the app's one retry), every region
RYW_MAX = 0  # reads that missed the user's own acknowledged write
AT_RISK_MAX = 0  # acknowledged writes only one region holds (lost if that region never comes back)


def stage_of(read_ok: bool, write_ok: bool, ryw_ok: bool, available_ok: bool, risk_ok: bool) -> int:
    """Judge the stage from the first incident (the primary region, us, is cut off from eu and ap):
    0 one primary region (far users read across an ocean), 1 read replicas in every region (fast
    reads, but writes wait for a retry across an ocean, users miss their own writes, writes have one
    copy), 2 writes in every region, acknowledged with two copies, with session tokens."""
    if not read_ok:
        return 0
    if not (write_ok and ryw_ok and available_ok and risk_ok):
        return 1
    return 2

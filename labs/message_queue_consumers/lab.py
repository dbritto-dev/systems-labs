"""Lab message_queue_consumers: the numbers and how the stage is judged. The words are in text/<lang>.py."""

from core.contract import Param

META = {
    "id": "message_queue_consumers",
    "params": {"rate": Param(40.0)},
}

PROCESSES = 7  # worker processes
SLOTS = 6  # messages each process works on at once
BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
AFTER = 5.0  # messages sent this long after an incident are judged too
SETTLE = 12.0  # wait this long after a window for redeliveries to finish
DLQ_SETTLE = 18.0  # ... and this long for poison to go through every retry to the DLQ

BASELINE_MIN = 0.99  # jobs done before the incident
DUP_MAX = 0.01  # share of jobs worked on twice (at once, or after they were done)
AGE_MAX = 1.0  # seconds, p99 of how long a message waits before a worker first picks it up
PARK_MIN = 0.95  # share of poison messages parked in the DLQ


def stage_of(baseline_ok: bool, lost_ok: bool, dup_ok: bool, age_ok: bool, dlq_ok: bool) -> int:
    """Judge the stage from what the first incident (a poison batch) did: 0 acks on receipt,
    1 acks after the work with a heartbeat, 2 bounded retries with backoff and a DLQ."""
    if not (lost_ok and dup_ok):
        return 0
    if not dlq_ok:
        return 1
    return 2

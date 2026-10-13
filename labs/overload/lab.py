"""Lab overload: the numbers, the goals and the stages."""

from core.contract import Param

META = {
    "id": "overload",
    "title": "Overload & queues",
    "summary": "A spike fills the queue with users who already left. Shed load so the server recovers.",
    "params": {
        "rate": Param(75.0, "users per second (each waits 1 s, then retries up to twice)"),
    },
}

CAPACITY = 100.0  # requests/s the server does at full speed
QUEUE_SHOWN = 500.0  # queue length that fills the server gauge
BASELINE_WINDOW = 15.0  # seconds before an incident used as the baseline
AFTER = 5.0  # waste is counted up to this long after an incident
RECOVERY = 5.0  # seconds the server may take to recover
RECOVERY_RUN = 3  # ...measured over this many seconds in a row
HORIZON = 15.0  # look this long after an incident for the recovery

BASELINE_MIN = 0.95  # first tries answered in time before the incident
QUEUE_MAX = 250  # longest queue allowed during the incident
WASTE_MAX = 0.05  # share of the work done for users who had already left
GOODPUT_MIN = 0.80  # replies in time vs what the server could do (or what users asked)
FAST_MAX = 0.300  # median time to an in-time reply, seconds
RECOVERED_MIN = 0.90  # share of first tries answered in time, to count as recovered

STAGES = [
    ("Unbounded FIFO",
     "Challenge: after a spike the queue fills with users who left, and it never recovers.",
     "Stage 1: reject at the door when the queue is full"),
    ("Bounded queue",
     "Challenge: the queue is bounded, but the server still works for users who already left.",
     "Stage 2: skip requests that are too late to answer"),
    ("Skip late requests",
     "Challenge: no wasted work, but every reply arrives just before users give up. Serve fresh.",
     "Stage 3: newest first while the queue is long"),
    ("Adaptive LIFO",
     "Solved: the queue is bounded, nothing is wasted, and the newest users get quick replies.",
     "All stages done"),
]


def stage_of(baseline_ok: bool, queue_ok: bool, waste_ok: bool, goodput_ok: bool, fast_ok: bool,
             recovered_ok: bool) -> int:
    """Judge the stage from what the first incident did."""
    for stage, ok in enumerate((queue_ok, waste_ok, fast_ok)):
        if not ok:
            return stage
    return 3

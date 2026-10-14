"""Shared pieces for the adapters."""

from __future__ import annotations

from live.canvas import BLUE, EXTRA1, EXTRA2, EXTRA3, GREEN, RED, WHITE
from live.views.lanes import slot

FLY = 0.35  # seconds a dot takes to reach the door (cosmetic: real calls take ~10 ms)
BACK = 0.4  # seconds an outcome stays at the door
FLIGHTS, OUTCOMES = 14, 8


def every(rows: list, most: int) -> list:
    """At most `most` rows, evenly spread."""
    return rows[:: max(1, len(rows) // most)][:most]


# ---- the clients' view of a distributed lab (its lanes picture)

SLOW = (0.25, 0.5, 0.8)  # seconds a client has waited before it turns light, mid, deep orange


def op_id(start: float) -> int:
    """Client operations have no id: their start time is unique enough to place them."""
    return int(start * 1_000_003)


def client_lanes(run, t: float, users: int, table: str, start: int, end: int, bad) -> tuple:
    """Clients waiting (coloured by how long), requests flying to the door, answers fading at it.

    `table` holds one row per client operation, with `start` and `end` columns; `bad(row)` says
    whether its answer was an error or an anomaly (red) rather than fine (green).
    """
    waiting = {}
    for o in run.active(table, t, end):
        waited = t - o[start]
        colour = WHITE if waited < SLOW[0] else EXTRA1 if waited < SLOW[1] else EXTRA2 if waited < SLOW[2] else EXTRA3
        waiting[slot(op_id(o[start]), users)] = (colour, True)
    flying = run.rows(table, t - FLY, t + 1e-9)
    flights = [(slot(op_id(o[start]), users), (t - o[start]) / FLY, WHITE, False) for o in every(flying, FLIGHTS)]
    span = run.max_dur.get(table, 0.0)
    ended = [o for o in run.rows(table, t - BACK - span, t + 1e-9) if t - BACK <= o[end] <= t]
    outcomes = [(RED if bad(o) else GREEN, (t - o[end]) / BACK) for o in every(ended, OUTCOMES)]
    return waiting, flights, outcomes


def message_gauge(run, t: float, maximum: float) -> tuple[float, tuple[int, int, int]]:
    """The cluster's gauge: messages between nodes in the last second, against `maximum`."""
    fill = run.count("msgs", t - 1, t) / maximum
    return fill, EXTRA2 if fill > 0.8 else BLUE

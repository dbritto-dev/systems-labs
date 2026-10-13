"""Shared pieces for the lanes adapters."""

from __future__ import annotations

FLY = 0.35  # seconds a dot takes to reach the door (cosmetic: real calls take ~10 ms)
BACK = 0.4  # seconds an outcome stays at the door
FLIGHTS, OUTCOMES = 14, 8


def every(rows: list, most: int) -> list:
    """At most `most` rows, evenly spread."""
    return rows[:: max(1, len(rows) // most)][:most]

"""Laboratorio stream_windowing: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations

import math

WINDOW = 10.0
ALLOWED_DELAY = 2.0
ALLOWED_LATENESS = 30.0


def window_of(t: float) -> float:
    """El inicio de la ventana que contiene el instante t."""
    return math.floor(t / WINDOW) * WINDOW


class Windower:
    """Ventanas por tiempo del evento con marca de agua, retraso permitido con correcciones y una
    salida lateral."""

    def __init__(self, sink) -> None:
        self.sink = sink
        self.windows: dict[float, int] = {}
        self.fired: set[float] = set()
        self.max_seen = -math.inf
        self.dropped = 0

    def on_event(self, event, now: float) -> None:
        self.max_seen = max(self.max_seen, event.time)
        start = window_of(event.time)  # cuándo ocurrió, no cuándo llegó
        if self.too_late(start):
            self.sink.side_output(event)  # ya no admite correcciones: apártalo, nunca lo descartes sin avisar
        else:
            self.windows[start] = self.windows.get(start, 0) + 1
            if start in self.fired:  # ya está en el panel: publica la cuenta corregida
                self.sink.emit(start, self.windows[start])
        self.close_ready()
        self.evict()

    def watermark(self) -> float:
        return self.max_seen - ALLOWED_DELAY

    def close_ready(self) -> None:
        wm = self.watermark()
        for start in sorted(self.windows):
            if start + WINDOW <= wm and start not in self.fired:
                self.sink.emit(start, self.windows[start])  # el primer resultado, en cuanto toca
                self.fired.add(start)  # ... pero guarda la ventana para lo tardío

    def too_late(self, start: float) -> bool:
        return start + WINDOW + ALLOWED_LATENESS <= self.watermark()

    def evict(self) -> None:
        for start in [s for s in self.windows if self.too_late(s)]:
            del self.windows[start]  # estado acotado: ya nada puede cambiar esta ventana
            self.fired.discard(start)

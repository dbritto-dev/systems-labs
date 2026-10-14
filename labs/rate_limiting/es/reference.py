"""Laboratorio rate_limiting: una solución que funciona. Léela después de intentar es/main.py."""

from __future__ import annotations


class RateLimiter:
    def __init__(self, rate: float = 20.0, burst: float = 10.0, capacity: float = 150.0) -> None:
        self.rate = rate
        self.burst = burst
        self.capacity = capacity
        self.buckets: dict[int, tuple[float, float]] = {}  # cliente -> (tokens, último relleno)
        self.seen: dict[int, float] = {}  # cliente -> hora de su última petición

    def allow(self, client: int, now: float) -> bool:
        # Reparto justo: nunca prometas más de lo que el backend puede hacer, repartido
        # entre los clientes activos ahora mismo.
        self.seen[client] = now
        active = sum(1 for t in self.seen.values() if now - t < 2.0)
        rate = min(self.rate, self.capacity / max(1, active))
        burst = self.burst
        # Token bucket: rellena `rate` tokens por segundo, hasta `burst`.
        tokens, last = self.buckets.get(client, (burst, now))
        tokens = min(burst, tokens + (now - last) * rate)
        if tokens < 1.0:
            self.buckets[client] = (tokens, now)
            return False
        self.buckets[client] = (tokens - 1.0, now)
        return True

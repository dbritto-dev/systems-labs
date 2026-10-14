"""Laboratorio hot_partition: una solución que funciona. Léela después de intentar main.py."""

from __future__ import annotations

import asyncio
import math
import random
from collections import deque

from labs.hot_partition.api import PARTITIONS, Throttled, now, salted

WINDOW = 0.25  # segundos de operaciones recientes que cuenta heat()
HOT = 50.0  # escrituras/s en una clave que la calientan: un tercio de lo que atiende una partición
SALTS = PARTITIONS  # etapa 1: subclaves por clave caliente, una en cada partición
PER_SALT = 30.0  # etapa 2: escrituras/s que debe recibir cada subclave, como mucho
COOL = 25.0  # etapa 2: por debajo de estas escrituras/s una clave repartida está fría ...
COOL_FOR = 2.0  # ... y si sigue así este tiempo, vuelve a juntar sus subclaves en la clave
GRACE = 1.0  # etapa 2: espera esto tras la última escritura a una subclave antes de juntarla
READ_HOT = 50.0  # etapa 2: lecturas/s que calientan las lecturas de una clave: sírvelas de la caché
CACHE_TTL = 0.5  # etapa 2: segundos que se sirve una cuenta guardada en la caché


class Counters:
    def __init__(self, store, rng: random.Random | None = None) -> None:
        self.store = store
        self.rng = rng or random.Random(0)
        self.recent: dict[tuple[str, str], deque] = {}  # (key, "w" o "r") -> momentos recientes
        self.width: dict[str, int] = {}  # claves repartidas: cuántas subclaves guardan parte de la cuenta
        self.writing: dict[str, int] = {}  # claves repartidas: a cuántas subclaves van las escrituras nuevas
        self.calm_since: dict[str, float] = {}
        self.cache: dict[str, tuple[float, int]] = {}

    async def incr(self, key: str) -> None:
        rate = self.heat(key, "w")
        if rate >= HOT:  # caliente de escrituras: repártela (más ancha si se calentó más)
            self.salt(key, rate)
        elif key in self.width:  # repartida, y quizá ya fría
            self.cool(key, rate)
        await self.store.incr(self.pick(key))

    async def read(self, key: str) -> int:
        hot = self.heat(key, "r") >= READ_HOT or key in self.width  # una suma de subclaves también merece la caché
        if hot:
            cached = self.cache.get(key)
            if cached is not None and now() - cached[0] < CACHE_TTL:
                return cached[1]  # una cuenta de CACHE_TTL como mucho: ninguna petición
        value = sum(await asyncio.gather(*(self.store.get(k) for k in self.keys_of(key))))
        if hot:
            self.cache[key] = (now(), value)
        else:
            self.cache.pop(key, None)
        return value

    def keys_of(self, key: str) -> list[str]:
        return [salted(key, i) for i in range(self.width.get(key, 1))]

    def heat(self, key: str, op: str) -> float:
        times = self.recent.setdefault((key, op), deque())
        t = now()
        times.append(t)
        while times[0] <= t - WINDOW:
            times.popleft()
        return len(times) / WINDOW

    def pick(self, key: str) -> str:
        n = self.writing.get(key, 1)
        return salted(key, self.rng.randrange(n)) if n > 1 else key

    def salts_for(self, rate: float) -> int:
        return max(2, min(PARTITIONS, math.ceil(rate / PER_SALT)))

    def salt(self, key: str, rate: float) -> None:
        n = max(self.width.get(key, 1), self.salts_for(rate))  # solo se ensancha mientras está repartida
        self.width[key] = self.writing[key] = n
        self.calm_since.pop(key, None)

    def cool(self, key: str, rate: float) -> None:
        if rate >= COOL:
            self.calm_since.pop(key, None)
            return
        since = self.calm_since.setdefault(key, now())
        if now() - since >= COOL_FOR and self.writing[key] > 1:
            self.writing[key] = 1  # las escrituras nuevas vuelven a la propia clave
            asyncio.ensure_future(self.fold(key))

    async def fold(self, key: str) -> None:
        await asyncio.sleep(GRACE)  # primero aterrizan las escrituras que ya iban a una subclave
        if self.writing.get(key, 1) > 1:
            return  # se volvió a calentar
        for i in range(1, self.width[key]):
            value = await _retry(lambda: self.store.take(salted(key, i)))  # ahora solo está en nuestras manos
            if value:
                await _retry(lambda: self.store.incr(key, value))
        if self.writing.get(key, 1) == 1:  # sigue fría: una sola clave vuelve a guardar toda la cuenta
            del self.width[key], self.writing[key]
            self.cache.pop(key, None)


async def _retry(call):
    while True:
        try:
            return await call()
        except Throttled:
            await asyncio.sleep(0.05)

"""Laboratorio hot_partition: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Un almacén clave/valor está repartido en seis particiones (p0 ... p5) según un hash de la clave;
cada una atiende 150 peticiones por segundo. Los usuarios dan me gusta, hacen clic y miran cosas:
cada me gusta es `Counters.incr(key)` y cada vez que se ve una cuenta es `Counters.read(key)`, ~120
operaciones por segundo sobre 5,000 claves. Repartido en seis particiones es fácil: cada una está
ocupada un ~15% del tiempo.

Entonces una clave explota: la publicación de una famosa se hace viral, todo el mundo hace clic en
el enlace de un boletín, una oferta relámpago vende un producto, un bot machaca un id. El hash
reparte claves, no tráfico: cada operación sobre esa clave cae en la misma partición. Rechaza
peticiones y da timeouts, mientras las otras cinco esperan.

Ahora mismo `Counters` manda cada operación a la propia clave.

Haz las etapas en orden, en este archivo:

  Etapa 1  Divide las claves calientes. Cuenta las escrituras recientes de cada clave (`heat`);
           cuando una clave se calienta, repártela: sus escrituras van a SALTS subclaves,
           salted(key, 0) ... salted(key, SALTS - 1), que el almacén pone en particiones distintas.
           Una lectura ahora tiene que sumar todas las subclaves: `keys_of(key)` las nombra, y
           `read` las suma.
  Etapa 2  Adaptativo. Reparte solo mientras está caliente, con N según el calor (`salts_for`);
           guarda la cuenta de una clave caliente CACHE_TTL segundos en una caché, para que sus
           lecturas dejen de ir a las particiones; y cuando la clave se enfríe, vuelve a juntar sus
           subclaves en la clave (`cool`, `fold`), para que sus lecturas dejen de sumar subclaves.
           No pierdas nunca un incremento.

Lo que tienes (mira labs/hot_partition/api.py):
  salted(key, i)                  la subclave i de key: "key#i"; salted(key, 0) es la propia key.
                                  La subclave i vive i particiones después de la de key, así que
                                  0 ... 5 caen en seis particiones distintas
  await store.incr(key, n=1)      suma n a un contador
  await store.get(key) -> int     lee un contador (0 si nunca se escribió)
  await store.take(key) -> int    lee un contador y lo deja a 0, en una sola petición
  now()                           el reloj, en segundos
Cada llamada al almacén es una petición a una partición. Una partición saturada lanza Throttled.

Compruébalo:  LABS_LANG=es uv run pytest labs/hot_partition
Mira una solución (¡después de intentarlo!):  labs/hot_partition/es/reference.py
"""

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
    """Contadores (me gusta, clics, unidades vendidas) sobre el almacén repartido. Cada operación de
    un usuario lo llama.

    Contrato:
      - `await incr(key)` suma 1 a la cuenta de key. Cuando vuelve, el incremento está confirmado
        al cliente: el almacén debe guardarlo. Si el almacén lanza Throttled, déjalo pasar (el
        usuario ve un error).
      - `await read(key)` devuelve la cuenta de key. Puede tener un poco de antigüedad (CACHE_TTL
        como mucho).
      - `keys_of(key)` lista cada clave del almacén que guarda parte de la cuenta de key ahora mismo.
        Se comprueba: las cuentas de esas claves deben sumar justo los incrementos confirmados.
      - Claves calientes: ninguna partición debería pasar del 90% de ocupación, y cuando nada está
        caliente una operación debería costar una petición, no una suma de subclaves.
    """

    def __init__(self, store, rng: random.Random | None = None) -> None:
        self.store = store
        self.rng = rng or random.Random(0)  # para pick(): las ejecuciones se repiten igual
        self.recent: dict[tuple[str, str], deque] = {}  # (key, "w" o "r") -> momentos recientes, para heat()
        self.width: dict[str, int] = {}  # claves repartidas: cuántas subclaves guardan parte de la cuenta
        self.writing: dict[str, int] = {}  # claves repartidas: a cuántas subclaves van las escrituras nuevas
        self.calm_since: dict[str, float] = {}  # claves repartidas: desde cuándo están bajo COOL (etapa 2)
        self.cache: dict[str, tuple[float, int]] = {}  # claves calientes: (cuándo, cuenta) (etapa 2)

    async def incr(self, key: str) -> None:
        # Etapa 1: `rate = self.heat(key, "w")`; cuando `rate >= HOT`, `self.salt(key, rate)`.
        #          Después escribe en `self.pick(key)` en vez de en key.
        # Etapa 2: si no está caliente pero está repartida (`key in self.width`), `self.cool(key, rate)`.
        await self.store.incr(key)

    async def read(self, key: str) -> int:
        # Etapa 1: nada que hacer aquí cuando keys_of nombra cada subclave: esto ya las suma.
        # Etapa 2: las lecturas de una clave están calientes cuando `self.heat(key, "r") >= READ_HOT`,
        #          o cuando está repartida. En ese caso devuelve la cuenta de `self.cache[key]` si
        #          tiene menos de CACHE_TTL segundos; si no, léela como abajo y guarda
        #          `self.cache[key] = (now(), value)`.
        values = await asyncio.gather(*(self.store.get(k) for k in self.keys_of(key)))
        return sum(values)

    def keys_of(self, key: str) -> list[str]:
        """Cada clave que guarda parte de la cuenta de key ahora mismo: key sola, o todas sus subclaves.

        Etapa 1: `[salted(key, i) for i in range(self.width.get(key, 1))]`.
        """
        return [key]

    def heat(self, key: str, op: str) -> float:
        """Etapa 1. Anota una operación sobre key (op es "w" para una escritura, "r" para una lectura)
        y devuelve cuántas tuvo por segundo en los últimos WINDOW segundos, esta incluida.

        Guarda los momentos en un deque, `self.recent.setdefault((key, op), deque())`: añade now(),
        quita por la izquierda los de hace más de WINDOW, y devuelve len / WINDOW.
        """
        raise NotImplementedError("PENDIENTE etapa 1: heat(key, op)")

    def pick(self, key: str) -> str:
        """Etapa 1. La clave a la que va una escritura: la propia key si no está repartida; si no, una
        de sus `self.writing[key]` subclaves al azar (`salted(key, self.rng.randrange(n))`)."""
        raise NotImplementedError("PENDIENTE etapa 1: pick(key)")

    def salt(self, key: str, rate: float) -> None:
        """Etapa 1. La clave está caliente: repártela. Pon `self.width[key]` y `self.writing[key]` a SALTS.

        Etapa 2: usa `self.salts_for(rate)`, pero nunca más estrecha de lo que ya es (una lectura
        tiene que seguir sumando cada subclave escrita hasta ahora), y olvida `self.calm_since[key]`.
        """
        raise NotImplementedError("PENDIENTE etapa 1: salt(key, rate)")

    def salts_for(self, rate: float) -> int:
        """Etapa 2. Cuántas subclaves necesita una clave con `rate` escrituras/s: rate / PER_SALT,
        redondeado hacia arriba, al menos 2 y como mucho PARTITIONS (más pondría dos subclaves en una
        misma partición)."""
        raise NotImplementedError("PENDIENTE etapa 2: salts_for(rate)")

    def cool(self, key: str, rate: float) -> None:
        """Etapa 2. Una clave repartida que no está caliente. Mientras `rate >= COOL`, olvida
        `self.calm_since[key]`. Bajo COOL, recuerda desde cuándo; cuando lleve COOL_FOR segundos en
        calma, manda las escrituras nuevas a la propia clave (`self.writing[key] = 1`) y lanza
        `self.fold(key)` como tarea (`asyncio.ensure_future`): esta llamada no debe esperarla."""
        raise NotImplementedError("PENDIENTE etapa 2: cool(key, rate)")

    async def fold(self, key: str) -> None:
        """Etapa 2. Vuelve a llevar las cuentas de las subclaves a la clave, sin perder ninguna.

        Primero `await asyncio.sleep(GRACE)`: aterrizan las escrituras que ya iban a una subclave. Si
        la clave se ha vuelto a calentar entretanto (`self.writing[key] > 1`), para. Si no, para cada
        subclave i desde 1: `value = await self.store.take(salted(key, i))`, y después
        `await self.store.incr(key, value)` (reintenta las dos si lanzan Throttled: un valor que has
        tomado solo está en tus manos). Al final, si sigue fría, olvida `self.width[key]` y
        `self.writing[key]`: las lecturas dejan de sumar subclaves.
        """
        raise NotImplementedError("PENDIENTE etapa 2: fold(key)")

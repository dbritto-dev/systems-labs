"""Laboratorio stream_windowing: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Un procesador de flujos cuenta compras por ventana de 10 segundos para un panel en vivo (y
para facturar). Cada evento lleva su tiempo del evento: cuándo ocurrió la compra, según el
reloj del teléfono o del servidor que la hizo. Los eventos llegan al procesador por un
canal (un registro con tres particiones), normalmente entre 0.05 y 1.5 s después y algo
desordenados. Cada uno llama a `Windower.on_event(event, now)`; tú envías los resultados al
panel con `self.sink.emit(start, count)`: la cuenta de la ventana que empieza en `start`.
Emitir otra vez la misma ventana reemplaza su cuenta (una corrección).

Ahora mismo el procesador cuenta por tiempo de proceso: la ventana de un evento es la que
está abierta cuando LLEGA. Los eventos que llegan un poco tarde caen en la ventana
siguiente, y cuando un lote llega minutos tarde (teléfonos que recuperan la conexión, una
partición atrasada, un reloj desfasado, una recarga de datos), cae entero en la ventana
equivocada. Los totales por ventana están mal.

Haz las etapas en orden, en este archivo:

  Etapa 1  Tiempo del evento con marca de agua: pon cada evento en la ventana de
           `event.time`. La marca de agua es el mayor tiempo del evento visto menos
           ALLOWED_DELAY; cuando pasa el final de una ventana, emite esa ventana y
           olvídala (`close_ready`). Un evento de una ventana ya cerrada se descarta y
           se cuenta en `self.dropped`.
  Etapa 2  Retraso permitido: guarda una ventana cerrada ALLOWED_LATENESS segundos más
           (en tiempo de marca de agua), y cuando un evento tardío cae en ella, cuéntalo y
           emite la cuenta corregida (una corrección). Un evento aún más tardío va a la
           salida lateral, `self.sink.side_output(event)`, para que nada se descarte sin
           avisar; luego olvida las ventanas así de viejas (`evict`), para que el estado
           siga siendo pequeño.

Compruébalo:  LABS_LANG=es uv run pytest labs/stream_windowing
Mira una solución (¡después de intentarlo!):  labs/stream_windowing/es/reference.py
"""

from __future__ import annotations

import math

WINDOW = 10.0  # segundos por ventana: [0, 10), [10, 20), ...
ALLOWED_DELAY = 2.0  # la marca de agua va esto por detrás del mayor tiempo del evento visto
ALLOWED_LATENESS = 30.0  # etapa 2: una ventana cerrada se guarda esto más (en tiempo de marca de agua)


def window_of(t: float) -> float:
    """El inicio de la ventana que contiene el instante t."""
    return math.floor(t / WINDOW) * WINDOW


class Windower:
    """Cuenta eventos por ventana y emite la cuenta de cada ventana al panel.

    Contrato:
      - `on_event(event, now)` se llama una vez por evento, en el orden en que llegan.
        `event.time` es su tiempo del evento, `event.id` su id; `now` es cuándo llegó
        (tiempo de proceso).
      - `self.sink.emit(start, count)` publica la cuenta de una ventana; emitir otra vez el
        mismo `start` la reemplaza (el panel muestra la última).
      - `self.sink.side_output(event)` aparta un evento que llega tarde para cualquier
        ventana, para que un proceso por lotes lo concilie después (etapa 2).
      - `self.windows` es tu estado: inicio de ventana -> cuenta, para cada ventana que aún
        guardas. El laboratorio mide el tamaño de tu estado como `len(self.windows)`.
    """

    def __init__(self, sink) -> None:
        self.sink = sink
        self.windows: dict[float, int] = {}  # inicio de ventana -> cuenta: el estado
        self.fired: set[float] = set()  # etapa 2: ventanas ya emitidas, guardadas para lo tardío
        self.max_seen = -math.inf  # etapa 1: el mayor tiempo del evento visto hasta ahora
        self.dropped = 0  # etapa 1: eventos tardíos descartados (una métrica, no los eventos)

    def on_event(self, event, now: float) -> None:
        # Etapa 1: cuenta por tiempo del evento:
        #     self.max_seen = max(self.max_seen, event.time)
        #     start = window_of(event.time)
        #     si start + WINDOW <= self.watermark(): la ventana ya cerró: self.dropped += 1
        #     si no: self.windows[start] = self.windows.get(start, 0) + 1
        #     y luego self.close_ready()
        # Etapa 2: si self.too_late(start): self.sink.side_output(event) en vez de contarlo;
        #          un evento tardío de una ventana en self.fired: cuéntalo y emite su nueva cuenta;
        #          después de close_ready(), llama a self.evict().
        for start in sorted(self.windows):  # tiempo de proceso: cierra lo que el reloj ya pasó
            if start + WINDOW <= now:
                self.sink.emit(start, self.windows.pop(start))
        start = window_of(now)  # la ventana abierta cuando LLEGÓ, no cuando ocurrió
        self.windows[start] = self.windows.get(start, 0) + 1

    def watermark(self) -> float:
        """Etapa 1. Hasta dónde llegó el tiempo del evento, menos el margen para los rezagados:
        `self.max_seen - ALLOWED_DELAY`. Sin eventos aún: -math.inf."""
        raise NotImplementedError("PENDIENTE etapa 1: watermark()")

    def close_ready(self) -> None:
        """Etapa 1. Emite cada ventana cuyo final (start + WINDOW) esté en la marca de agua o
        antes, de la más vieja a la más nueva, y quítala de self.windows.

        Etapa 2: no la quites: emítela una vez, añade su inicio a self.fired y guárdala para
        los eventos tardíos (evict() la quita más tarde)."""
        raise NotImplementedError("PENDIENTE etapa 1: close_ready()")

    def too_late(self, start: float) -> bool:
        """Etapa 2. True cuando la ventana que empieza en `start` ya pasó su retraso permitido:
        su final más ALLOWED_LATENESS está en la marca de agua o antes."""
        raise NotImplementedError("PENDIENTE etapa 2: too_late(start)")

    def evict(self) -> None:
        """Etapa 2. Olvida cada ventana que cumpla too_late(): quítala de self.windows y de
        self.fired. Los eventos tardíos para ella irán a la salida lateral."""
        raise NotImplementedError("PENDIENTE etapa 2: evict()")

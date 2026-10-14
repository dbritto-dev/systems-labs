# Laboratorio: ventanas en un flujo

*[Read in English](../README.md)*

Un procesador de flujos cuenta compras por ventana de 10 segundos para un panel en vivo (y
para facturar). Teléfonos y servidores hacen ~40 compras por segundo; cada evento lleva su
tiempo del evento (cuándo ocurrió la compra) y llega al procesador a través de un registro
con tres particiones, normalmente entre 0.05 y 1.5 s después y algo desordenado. El
procesador llama a tu `Windower.on_event(event, now)` por cada uno; publicas la cuenta de una
ventana con `self.sink.emit(start, count)` (emitir otra vez una ventana reemplaza su cuenta:
una corrección), y apartas eventos con `self.sink.side_output(event)`.

En momentos al azar, como en producción, los eventos llegan tarde: los teléfonos recuperan la
conexión y envían compras hechas hace de 6 s a minuto y medio (el metro, el modo avión, una app
suspendida, una caída de un operador móvil); una partición se atrasa de 5 a 20 s (una pausa de
GC en el broker, un disco lento, un reequilibrio, una partición saturada); el reloj de un
productor va de 10 a 45 s atrasado (sin NTP, una máquina virtual reanudada); o una recarga
reenvía eventos de hace 1 a 3 minutos. El primer incidente siempre son teléfonos que recuperan
la conexión entre 0:20 y 0:30, con eventos de hace 6 a 18 s.

```
uv run python -m live stream_windowing --lang es            # míralo; edita es/main.py y guarda
uv run python -m live stream_windowing --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/stream_windowing            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves (primer incidente, 12 semillas) |
|---|---|---|
| 0 Tiempo de proceso (dada) | cuenta cada evento en la ventana abierta cuando llega | incluso en calma los rezagados caen en la ventana siguiente (del 98.9 al 99.7% en la suya); el lote tardío cae en la ventana actual: del 0 al 25% de ventanas exactas, de 206 a 287 eventos fuera de su ventana |
| 1 Tiempo del evento + marca | `watermark()` = mayor tiempo del evento visto − `ALLOWED_DELAY`; cuenta por `event.time`; `close_ready()` emite una ventana cuando la marca de agua pasa su final; lo que llega después se descarta (`self.dropped`) | las ventanas en calma cuadran (100%), los primeros resultados llegan de 2.1 a 2.2 s tras el final de la ventana, pero el lote tardío se descarta: 50% de ventanas exactas, de 164 a 249 eventos descartados |
| 2 Retraso permitido + correcciones | guarda las ventanas emitidas (`self.fired`) hasta `too_late()`; un evento tardío corrige su ventana; uno aún más tardío va a `side_output`; `evict()` el resto | todas las ventanas exactas, 0 descartados, primeros resultados de 2.1 a 2.3 s, como mucho 5 ventanas guardadas |

Dos atajos tentadores también se quedan en la etapa 1: una marca de agua tan lenta como el
retraso permitido (`ALLOWED_DELAY = 32`) acierta todas las ventanas, pero el primer resultado
llega 32 s después del final de la ventana; guardar todas las ventanas para siempre (sin
`evict()`) también acierta, pero el estado crece sin límite (8 ventanas en el primer veredicto, unas
50 tras diez minutos).

Objetivos, juzgados por incidente: en calma ≥ 99.9% (los eventos que llegaron en los 20 s
anteriores, contados en su propia ventana; antes); ventanas exactas ≥ 99% (las ventanas desde
40 s antes del incidente hasta 10 s después cuya última cuenta coincide con los eventos de ese
tiempo del evento que llegaron dentro del retraso permitido; después, cuando son definitivas);
descartados = 0 (eventos que no están ni en la cuenta de su ventana ni en la salida lateral, en
esas ventanas y en cualquier ventana a la que pertenezca un evento que llegó durante el
incidente; después); latencia p99 ≤ 5 s (desde el final de una ventana hasta su primer
resultado, para las ventanas que terminan durante el incidente; durante); estado ≤ 6 ventanas
(el máximo de ventanas que guardó el procesador, desde el inicio del incidente hasta que sus
ventanas son definitivas; durante). El laboratorio juzga con su propia marca de agua (mayor
tiempo del evento visto − 2 s) y su retraso permitido (30 s), los mismos números que `es/main.py`.

**Dibujo de carriles** (el de inicio). Los teléfonos de la izquierda se encienden cuando llega
su evento: blanco a tiempo, de naranja claro a oscuro cuanto más tarde. Los eventos vuelan
hasta la puerta, que es la marca de agua del procesador: se vuelve roja y sólida mientras se
descartan eventos tardíos, azul mientras lo tardío corrige ventanas cerradas, morada mientras
lo muy tardío va a la salida lateral. Lo que pasó con cada evento se desvanece en la puerta:
verde contado, azul contado en una corrección, morado salida lateral, rojo descartado o contado
en otra ventana. El servidor es el procesador de ventanas; su indicador son las ventanas que
guarda, frente al límite de 6, y debajo la marca de agua. Las barras muestran las últimas
ventanas por tiempo del evento, divididas según lo que pasó con sus eventos; la gráfica muestra
los eventos por segundo de la misma forma.

**Dibujo del clúster.** Pulsa `v` (o `--view cluster`) para ver el canal como nodos en una
cuadrícula de 3x3: las tres particiones del registro en la columna izquierda (una se vuelve
naranja mientras va atrasada), el procesador y el panel arriba, el estado de ventanas del
procesador y la salida lateral debajo de ellos. Los productores envían eventos a las
particiones; los eventos siguen hasta el procesador, coloreados según lo tarde que llegan; las
cuentas vuelan al panel (verde la primera, azul una corrección) y lo muy tardío a la salida
lateral (morado). Los eventos descartados mueren en rojo de camino al procesador; el panel se
vuelve rojo mientras una ventana reciente está mal, y el nodo del estado naranja o rojo al
llegar al límite.

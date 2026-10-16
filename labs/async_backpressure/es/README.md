# Laboratorio: contrapresión en asyncio

*[Read in English](../README.md)*

Un proceso de ingesta hecho con asyncio. Un flujo de eventos le empuja ~1,000 eventos/s (30% HIGH:
pedidos, pagos; 70% LOW: clics, páginas vistas). Tu `Pipeline` los lee (la fuente), los analiza
(etapa A), los enriquece con un servicio (etapa B: ~25 ms por llamada, 8 llamadas a la vez) y los
escribe en una base de datos por lotes (etapa C: 15 ms + 0.1 ms por evento, una escritura a la
vez, como mucho 1,000 eventos). La memoria está modelada: cada evento que tiene el proceso cuesta
4 KiB crudo, 8 KiB analizado, 16 KiB enriquecido, además de 96 MiB del propio intérprete; el límite
del contenedor es 256 MiB, y si se pasa el kernel mata el proceso (OOM): todo evento que tenía se
pierde, y uno nuevo arranca 5 s después. Mientras nadie lee, el origen guarda lo que llega en su
búfer (5,000 eventos, ~5 s) y tira los más viejos cuando se llena: perdidos, y nadie te avisa. En
momentos al azar, como en producción, el destino va de 4 a 16 veces más lento (autovacuum, una
compactación, un límite de escrituras, una copia de seguridad), el servicio de enriquecimiento tiene
un pico de latencia (pausas del recolector de basura, una caché fría), el origen manda una ráfaga de
2 a 3 veces (una recarga histórica, algo que se vuelve viral), o el destino se cae de 4 a 12 s (un
cambio a la réplica, un certificado caducado). La ejecución nunca se reinicia. El primer incidente
es siempre el destino 16 veces más lento entre 0:20 y 0:50.

```
LABS_LANG=es uv run python -m live async_backpressure          # míralo; edita es/main.py y guarda
LABS_LANG=es uv run python -m live async_backpressure --lesson # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/async_backpressure             # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves en el primer incidente |
|---|---|---|
| 0 Colas sin límite (dada) | `asyncio.Queue()` entre las etapas, escrituras de 50 | la cola delante del destino crece ~13 MiB/s; a los ~12 s matan el proceso por falta de memoria (2 veces, ~21,000 eventos perdidos), caudal ~20% de lo que admitiría el destino lento |
| 1 Colas acotadas | `asyncio.Queue(maxsize=QUEUE_SIZE)`: `put` espera, la fuente deja de leer | sin muertes, memoria plana (~51%); pero el búfer del origen se desborda: ~19,000–20,000 eventos perdidos en silencio, y las escrituras de 50 sacan ~29% de lo que admitiría el destino |
| 2 Créditos + lotes adaptativos | ventanas de `Credits` en cada enlace, `take_batch`, `admit` descarta LOW (contados) y guarda una reserva para HIGH | pico ~57%, 0 perdidos, ~500 eventos LOW/s descartados (contados), todos los HIGH escritos, lotes de 1.000, caudal 93–98%, p99 de vuelta a ~60 ms justo después |

Objetivos, evaluados por incidente: base correcta (eventos escritos frente a llegados, antes), sin
memoria = 0 (muertes del proceso), perdidos = 0 (tirados por el origen, muertos con el proceso o
HIGH descartados), pico de memoria ≤ 80% del límite (estos tres hasta 10 s después del incidente),
caudal ≥ 80% (eventos escritos frente a lo que llegó, o lo mejor del servicio más lento si es menos),
y el p99 de punta a punta de los eventos que llegan entre 5 y 20 s después del incidente < 1 s (se
recupera).

Dos dibujos: `lanes` (el primero) muestra uno de cada diez eventos: espera (blanco, luego naranja
más oscuro cuanto más espera, en el origen o en una cola), vuela a la puerta (la fuente) cuando se
lee, y allí se desvanece con su resultado: verde escrito, gris descartado (LOW, contado), rojo perdido. La
puerta se cierra cuando la fuente no da abasto (el origen guarda un atraso) y se pone roja mientras
el proceso arranca de nuevo; el indicador del servidor es la memoria del proceso (naranja por encima
del 80%). `cluster` pone la fuente, A, B, C y el destino en una fila: los eventos vuelan por ella,
cada etapa se colorea por cuántos eventos tiene (azul, luego naranja más oscuro) y lleva esa cuenta
debajo, la fuente lo que espera en el origen, el destino su velocidad (o CAÍDO, o cuántas veces más
lento); pulsa `v` para cambiar.

- **Por qué una cola sin límite es una fuga de memoria con retraso.** Una cola entre una etapa rápida
  y una lenta crece a la diferencia de sus ritmos. Entran 1,000 eventos/s, salen 156/s, 16 KiB cada
  uno: 13 MiB por segundo, y el kernel no pregunta qué eventos importan.
- **Por qué las colas acotadas mueven el problema.** `put` espera, las esperas viajan hasta la
  fuente, la fuente deja de leer y el atraso queda en el origen. Un log durable (Kafka) puede
  esperar horas; un flujo que empuja tiene unos segundos de búfer y luego tira. Pausar es una decisión
  que depende del origen: sabe cuál tienes.
- **Por qué créditos.** Una cola acotada acota lo que espera, no lo que una etapa tiene en las manos
  (el lote que se escribe, las llamadas en curso). Los créditos se devuelven solo cuando los eventos
  han seguido su camino, así que acotan las dos cosas, y la fuente puede preguntar cuánto sitio queda
  (`free`) en vez de solo bloquearse.
- **Por qué lotes adaptativos.** Una escritura cuesta 15 ms más 0.1 ms por evento; 16 veces más
  lenta, un lote de 50 tarda 320 ms (156 eventos/s) y uno de 1,000 tarda 1.8 s (543 eventos/s). Toma lo
  que hay en cola: lotes pequeños cuando el destino va rápido, grandes cuando va lento.
- **Por qué descartar LOW, contado.** Cuando ni los lotes llenos alcanzan, algo cede. Elígelo tú:
  descarta la clase de baja prioridad en la puerta, cuéntala, y guarda una reserva de la ventana para
  que los HIGH sigan entrando mientras el destino está caído unos segundos.

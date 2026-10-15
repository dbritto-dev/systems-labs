# systems-labs

*[Read in English](README.md)*

Aprende cómo se comportan los sistemas backend y distribuidos haciéndolo. Hay **45
laboratorios**, cada uno un problema: reintentos, balanceo de carga, plazos, autoescalado, caché, consultas
e índices, migraciones, paginación, colas, bandejas de salida, webhooks y sagas, flujos de eventos,
asyncio, interbloqueos, replicación, particionado, cerrojos, consenso y los retos Gossip Glomers de Fly.io. Reproduces el problema, lo arreglas en tu propio archivo y **lo ves en
vivo en la terminal** mientras se ejecuta. La herramienta no supone ningún tema: un
laboratorio de caché encaja igual que uno de reintentos.

Python puro: solo la biblioteca estándar, sin dependencias en tiempo de ejecución.
Python 3.13+.

## Instalar y ejecutar

```sh
uv sync                                              # Python 3.13 + pytest
uv run python -m live --lang es                      # lista los laboratorios
uv run python -m live retry_storm --lang es          # abre uno; edita su es/main.py y guarda
uv run python -m live caching --lang es --lesson       # el concepto, enlaces y una lista de comprobación
uv run python -m live caching --lang es --at 90 --size 110x44 --color   # imprime un fotograma
LABS_LANG=es uv run pytest                           # x = tu código aún no está, X = hecho
LABS_SLOW=1 uv run pytest labs/test_long_runs.py     # cada solución, 30 minutos con 3 semillas
LABS_LANG=es LABS_REFERENCE=1 uv run pytest          # comprueba las soluciones de referencia
LABS_LANG=es LABS_STRICT=1 uv run pytest             # el control del repo: los tests del código inicial siguen estrictos
```

Con `LABS_LANG=es` en el entorno no hace falta `--lang es`. Más opciones: `--set
nombre=valor` cambia un parámetro del laboratorio (`--set rate=150`), `--variant
reference` muestra la solución, `--variant ruta/a/archivo.py` muestra cualquier archivo con
los mismos nombres, `--seed N` elige otros momentos para los incidentes, `--view NOMBRE`
abre otro dibujo del laboratorio (la tecla `v` cambia mientras se ejecuta).

## Idiomas

Cada laboratorio funciona en **inglés** o **español**: `--lang es`, o `LABS_LANG=es` para
todo (el visor, `--lesson`, los tests). Está todo traducido, también el archivo que editas:
en español trabajas en `labs/<lab>/es/main.py` (el mismo código y los mismos nombres, con
comentarios y pistas en español; también `es/reference.py` y `es/README.md`).

Las palabras viven en catálogos, uno por idioma, con los mismos nombres en cada uno:

```
live/text/en.py, es.py           la pantalla: menús, títulos del panel, la pantalla de carga…
core/text/en.py, es.py           mensajes de core/ (cargar tu código, --set)
labs/<lab>/text/en.py, es.py     un laboratorio: título, etapas, objetivos, causas, lección…
```

Un test (`core/test_i18n.py`) comprueba que cada idioma tiene cada nombre, clave y
`{marcador}`, y que las palabras caben en la pantalla. La simulación nunca depende del
idioma: una traza guarda claves (una causa es `"bad_deploy"`) y solo la pantalla las
convierte en palabras. Para añadir un idioma: copia cada `en.py` a `<código>.py`,
tradúcelo, copia la carpeta `es/` de cada laboratorio a `<código>/` y añade el código a
`core.i18n.LANGS`.

## Cómo funciona un laboratorio

- **Tu archivo** es `labs/<lab>/es/main.py` (`labs/<lab>/main.py` en inglés). Funciona en la
  etapa 0 y tiene contratos en los docstrings, pistas y huecos `NotImplementedError("PENDIENTE
  …")` para las etapas que construyes, en orden, en ese único archivo. `es/reference.py`
  tiene los mismos nombres, funcionando.
- **Tiempo virtual.** Un laboratorio es código `asyncio` sobre un reloj virtual
  (`core.vtime.VirtualRun`): cuando no hay nada listo, el reloj salta al siguiente
  temporizador. Un minuto de tráfico se ejecuta en un segundo más o menos, y siempre igual.
- **Una ejecución sin fin.** Una ejecución es una sola simulación que no se reinicia hasta
  que sales, repites o guardas: presupuestos de reintentos, contenido de la caché y colas
  siguen de un minuto al siguiente. Corre en un proceso hijo (tu código nunca corre en el
  proceso de la ventana), que le pasa a la ventana el minuto siguiente en segundo plano, con
  20 s por minuto antes de detenerse. Los errores salen en pantalla con el archivo que hay
  que editar. La ventana guarda los últimos 5 minutos para moverte por ellos, y los totales
  para siempre.
- **Incidentes al azar, como en producción.** Los usuarios no dejan de llegar (el tráfico
  varía despacio, ±15%) y las cosas fallan al azar: los intervalos varían, las duraciones
  tienen una cola larga, los incidentes cruzan los límites de cada minuto, y cada uno tiene
  una causa (un despliegue malo, un certificado caducado, una réplica muerta, un nodo de
  caché reiniciado…). Solo el primer incidente es fijo (0:20), así el primer veredicto es
  estable; `--seed N` da otro día de producción.
- **Recarga en caliente.** Guarda cualquier archivo de `labs/<lab>/` (o pulsa `r`): se vuelve
  a ejecutar desde 0:00. El dibujo anterior se queda hasta que llega la nueva ejecución.
- **La etapa se juzga por lo que hizo tu código**, nunca leyéndolo.

## La pantalla

```
Tormenta de reintentos                                         ▶ 1:40  1x   ← reloj
Reto: los reintentos vuelven al instante y machacan el servicio. …          ← qué arreglar
Ahora: Reintentos   → Etapa 2: espera backoff_delay(attempt) entre reintentos
                                           ▍Carga <1.5x ▍Reint. ≥3% ▍Servido ≥90%
 ○ ○ ● ○ ○                                    4.0x        75%          42%
 ○ ● ○ ○ ○   · ·  · ┃ ·   ┌─────────┐       ▃▃▃▃▃█      ▁▁▁▁▅█       ███▆▁
 ○ ○ ○ ○ ●           ┃     │ ▬▬▬   ▓ │      ▍Usuarios …  ▍Llamadas …
                           └─────────┘      ▍Caída n.º 2  ● OK / ● ALERTA / ○ ESPERA
                              CAÍDO         ▍Eventos  SIG. …   leyenda
 ▁▂▃▅█  gráfica: los últimos 60 s por segundo, el límite discontinuo, incidentes sombreados
Edita labs/retry_storm/es/main.py y guarda: esta ventana lo vuelve a ejecutar.
pausa/sigue [space] - reinicia [0] - repite [r] - vista [v] - sal [q]
```

- **Cabecera**: el laboratorio, el reloj (`▶` en marcha, `❚❚` en pausa, `…` simulando por
  delante), el reto de la etapa en la que está tu código y el siguiente paso.
- **Dibujo (carriles)**: los usuarios a la izquierda, un carácter cada uno: `○` tenue en
  reposo, `●` esperando, con color según cuánto trabajo extra cuesta su petición (blanco =
  ninguno, naranja más intenso = más). Los puntos viajan hasta una **puerta** (lo que está
  delante del servidor: un gateway, una caché, una cola): barra roja sólida cuando está
  cerrada, punteada cuando está abierta. Los resultados se desvanecen en la puerta (verde
  servida, rojo fallida). El servidor es una caja con tres bahías de disco y un indicador; su
  estado va centrado debajo. Los puntos son una muestra del tráfico, más lentos para que se
  vean: esa parte es estética.
- **Dibujo (clúster)**, en los laboratorios distribuidos: los nodos en una cuadrícula, los
  mensajes viajando entre ellos, los perdidos en rojo, y una partición como un corte rojo.
- **Tarjetas**: tres números con sus objetivos. El fondo es verde cuando va bien, naranja
  cuando se acerca y rojo solo cuando cruza un límite. Las barritas de abajo son los últimos
  30 s: cada una es el peor segundo de su tramo.
- **Usuarios**: servidos, fallidos, esperando, y las esperas p50/p99 de los últimos 5 s.
- **Por segundo**: lo que piden los usuarios frente a lo que recibe el servidor, apilado
  por trabajo extra, con la marca del límite y un titular de una frase.
- **Objetivos**: se evalúan en cada incidente (`Caída n.º 3`), antes / durante / después.
  `○ ESPERA` hasta que se cierra su ventana, `● OK`, o `● ALERTA` (antes de tiempo solo cuando
  ya no puede cumplirse). No se muestra nada antes de que llegue el cabezal.
- **Eventos**: los más nuevos primero, con la última alerta abierta fijada junto a su
  arreglo, y una fila `SIG.` con la siguiente comprobación. Nunca algo que aún no ha pasado.
- **Gráfica**: los últimos 60 s, con los colores del dibujo, el límite discontinuo y los
  incidentes sombreados.

Colores: blanco = primeros intentos y peticiones normales; naranja claro, medio e intenso
= trabajo extra (una ronda de reintentos, un fallo de caché, una carga duplicada); rojo =
fallida; verde = servida; azul = sano/arreglado.

Teclas: `space` pausa/sigue, `0` reinicia desde 0:00, `r` repite, `v` el siguiente dibujo
(si el laboratorio tiene más de uno), `q` sal, `← →` avanza o retrocede 5 s, `↑ ↓` velocidad, `d` una línea de depuración (tiempo por fotograma, fps, cuánto va por delante la simulación).
La pantalla necesita al menos 92x27 (si no, un mensaje de una línea), usa hasta 124 columnas
y se ve mejor desde 110x44.

## Laboratorios

Hay 45 laboratorios. Cada uno tiene dos dibujos, **carriles** (usuarios, una puerta, un
servidor) y **clúster** (nodos y los mensajes entre ellos), y abre con el que mejor lo
explica; pulsa `v` para cambiar. Algunos tienen además una variación de carriles: **relevo**
pone un segundo servidor en medio (un balanceador, una pasarela, una caché, una cola) y las
peticiones van usuario → puerta → relevo → servidor; **abanico** hace que el relevo llame a
varios servidores pequeños, cada uno con su indicador (un orquestador y sus servicios, un
coordinador y sus fragmentos).

Cada uno de estos laboratorios abre con ese dibujo.

| Dibujo | Laboratorios |
|---|---|
| relevo | `load_balancing`, `rate_limiting`, `graceful_shutdown`, `autoscaling`, `canary_releases`, `circuit_breaker`, `hedged_requests`, `connection_pool`, `idempotency`, `caching`, `cache_invalidation`, `n_plus_one_queries`, `zero_downtime_migration`, `message_queue_consumers` |
| abanico | `saga_orchestration`, `webhook_delivery`, `two_phase_commit`, `hot_partition`, `replication_lag`, `quorum_replication` |

Tráfico y fiabilidad:

| Laboratorio | Problema | Etapas |
|---|---|---|
| `retry_storm` | el servicio se cae; los reintentos se acumulan | reintentos → backoff → jitter → presupuesto de reintentos |
| `rate_limiting` | unos pocos clientes inundan la API | ventana fija → token bucket → bucket + reparto justo |
| `connection_pool` | la base de datos se ralentiza o llega un pico de tráfico | pool → pool acotado → timeout al pedir conexión |
| `circuit_breaker` | una dependencia se vuelve muy lenta y arrastra al resto | timeouts → bulkhead → circuit breaker |
| `overload` | un pico de tráfico; la cola nunca se recupera (metaestable) | cola acotada → saltar peticiones tardías → LIFO adaptativo |
| `load_balancing` | uno de 8 servidores se vuelve lento pero sigue recibiendo su parte | por turnos → menos pendientes → dos opciones al azar |
| `hedged_requests` | pocas respuestas lentas marcan el p99; una réplica se vuelve lenta | una llamada → copia tras el p95 → presupuesto de copias + cancelar la perdedora |
| `deadline_propagation` | una cadena de servicios sigue trabajando cuando el usuario ya se fue | timeout por salto → pasar el plazo → saltar el trabajo tardío |
| `graceful_shutdown` | los despliegues cortan peticiones en curso | salir al instante → drenar → primero dejar de estar listo, luego drenar |
| `autoscaling` | el tráfico sube y baja; escalar tarde u oscilar | flota fija → umbrales de CPU → seguimiento de objetivo con enfriamiento y calentamiento |
| `canary_releases` | una versión mala llega a los usuarios: caídas, errores, latencia, una sola ruta | desplegar en todo → canario con umbral fijo → comparar con la base, rampa por etapas, vuelta atrás automática |

Datos y mensajería:

| Laboratorio | Problema | Etapas |
|---|---|---|
| `caching` | una base de datos lenta; después, una caché vaciada | cache-aside con TTL → single-flight + TTL con jitter |
| `cache_invalidation` | escrituras y rellenos de caché compiten; quedan valores viejos | caché y luego BD → escribir y luego borrar → rellenos con concesión (versión) |
| `idempotency` | los pagos se reintentan y llegan dos veces | repetir respuestas guardadas → reservar la clave antes de cobrar |
| `n_plus_one_queries` | una página consulta la base de datos una vez por elemento | N+1 → una consulta IN agrupada → un JOIN |
| `database_index` | la tabla no deja de crecer; cada consulta la lee entera | índice hash → índice hash + compuesto |
| `keyset_pagination` | los usuarios pasan páginas mientras entran y salen filas | OFFSET → keyset por created_at → cursor opaco (created_at, id) |
| `optimistic_locking` | muchas peticiones leen, cambian y escriben las mismas filas | gana la última escritura → control de versión → reintento con relectura y backoff con jitter |
| `zero_downtime_migration` | renombrar una columna mientras corren el código viejo y el nuevo | cambio en el sitio → expandir/contraer → relleno por lotes con freno |
| `transactional_outbox` | guardar un pedido y anunciarlo; el proceso muere entre medias | doble escritura → bandeja de salida + relé → consumidor idempotente |
| `message_queue_consumers` | los workers se caen, los trabajos van lentos, llegan mensajes venenosos | confirmar al recibir → confirmar al terminar + latido → backoff + cola de mensajes muertos |
| `saga_orchestration` | un pedido abarca pagos, inventario y envío; un paso falla | sin deshacer → compensaciones → sagas idempotentes y reanudables |
| `stream_windowing` | contar eventos por ventana cuando llegan tarde | tiempo de proceso → tiempo del evento + marcas de agua → retraso permitido + correcciones |
| `webhook_delivery` | los destinos de los clientes se caen, se cuelgan, van lentos o rechazan un evento | enviar una vez → reintentos con backoff → una cola por destino, en orden por clave, con pausa |

Concurrencia (asyncio y cerrojos):

| Laboratorio | Problema | Etapas |
|---|---|---|
| `event_loop_blocking` | una llamada bloqueante frena todas las peticiones del bucle | llamadas síncronas → to_thread → grupos de hilos y procesos acotados + vigilante del retardo |
| `async_backpressure` | un productor rápido y un destino lento: la memoria crece hasta el OOM | colas sin límite → colas acotadas → créditos, lotes adaptativos, descartes contados |
| `deadlock_avoidance` | las transferencias bloquean dos cuentas y el servicio se congela | bloquear en el orden de la petición → timeouts con reintento → un orden global |

Sistemas distribuidos: los retos [Gossip Glomers](https://fly.io/dist-sys/) de Fly.io sobre
una red simulada con particiones:

| Laboratorio | Reto | Etapas |
|---|---|---|
| `unique_id_generation` | n.º 1 Echo, n.º 2 IDs únicos | echo → IDs únicos → IDs Snowflake (64 bits, ordenados en el tiempo, resisten saltos de reloj) |
| `broadcast` | n.º 3 Broadcast | varios nodos → tolerante a fallos → eficiente → por lotes (3b–3e) |
| `grow_only_counter` | n.º 4 Contador solo creciente | clave compartida → compare-and-swap → una clave por nodo, sobre seq-kv |
| `kafka_style_log` | n.º 5 Log al estilo Kafka | un nodo → varios nodos con lin-kv → eficiente: un dueño por clave (5a–5c) |
| `transactions` | n.º 6 Transacciones siempre disponibles | replicado → lectura no confirmada → lectura confirmada (6a–6c) |

Replicación, particionado y coordinación, sobre la misma red:

| Laboratorio | Problema | Etapas |
|---|---|---|
| `replication_lag` | las lecturas van a réplicas que se quedan atrás | lee tus escrituras → lecturas monótonas |
| `consistent_hashing` | los servidores de caché entran y salen; las claves se mueven | módulo → anillo de hash → anillo + nodos virtuales |
| `geo_replication` | usuarios en 3 regiones; una región cae o queda aislada | una región primaria → réplicas de lectura → escrituras en cada región + tokens de sesión |
| `hot_partition` | una clave explota y satura su partición | hash por clave → repartir claves calientes → reparto adaptativo + caché |
| `quorum_replication` | cada clave en 3 de 5 nodos; un nodo se cae | una copia → quórums (R + W > N) → quórums + reparación en lectura |
| `chain_replication` | una cadena de 4 réplicas; un nodo cae, va lento o entra | primario-respaldo → cadena → cadena con reparación |
| `merkle_anti_entropy` | las réplicas divergen en silencio: escrituras perdidas, discos malos, copias viejas | sin reparación → barrido completo → árboles de Merkle |
| `vector_clocks_crdts` | las réplicas aceptan escrituras durante una partición y luego se unen | gana la última escritura → relojes vectoriales → un CRDT (OR-set) |
| `failure_detection` | detectar un nodo caído; no dar nunca por muerto a uno lento | timeout fijo → phi accrual → SWIM |
| `distributed_lock` | quien tiene el cerrojo se congela y despierta escribiendo | cerrojo simple → plazos (leases) → tokens de vallado |
| `two_phase_commit` | una transferencia toca 3 fragmentos; el coordinador se cae | un fragmento cada vez → 2PC → 2PC con registro de decisiones y recuperación |
| `raft_consensus` | elegir un líder; no perder nunca un comando consolidado | elección de líder → replicación del log → seguro (términos, votos al día) |
| `paxos_consensus` | varios nodos proponen; el líder cae a mitad de ronda | gana la primera propuesta → Paxos por hueco → Multi-Paxos |

## Estructura

```
core/   vtime.py (asyncio con tiempo virtual)  services.py (servicios simulados)
        net.py (una red al estilo Maelstrom: nodos, RPC, latencia, particiones, seq-kv/lin-kv)
        incidents.py (incidentes al azar, tráfico que varía)  contract.py (carga el código
        del laboratorio, los descubre, --set)  i18n.py (idiomas, catálogos)  text/ (las
        palabras de core)  lessons.py  testing.py
labs/   <lab>/ main.py  reference.py  README.md     tus archivos, en inglés
               es/ main.py  reference.py  README.md  lo mismo, en español
               text/ en.py  es.py                    cada palabra que muestra el laboratorio
               scenario.py  lab.py (números, stage_of)  test_lab.py
live/   canvas.py (Braille + color)  screen.py (terminal)  runner.py (procesos hijo, Feed)
        frame.py (cabecera, gráfica, pie)  panel.py (panel)  text/ (las palabras de la pantalla)
        views/ (View, Adapter: lanes, cluster, y las variaciones de carriles relay, fanout)
        adapters/ (un módulo por laboratorio)
        worlds/ (un World por laboratorio)  viewer.py (el bucle: estados, comandos de teclas, avisos,
        redibujar solo si cambia)  __main__.py  views/parts.py (las piezas de los dibujos)
```

## Añadir un laboratorio

1. **`labs/<lab>/`** con:
   - `main.py`: la etapa 0 funcionando y el resto como contratos y huecos
     `NotImplementedError`; `reference.py`: los mismos nombres, funcionando; `README.md`;
   - `es/main.py`, `es/reference.py`, `es/README.md`: el mismo código y los mismos nombres,
     con comentarios y pistas en español (un test comprueba que los nombres coinciden);
   - `text/en.py` y `text/es.py`: cada palabra que muestra el laboratorio: `TITLE`,
     `SUMMARY`, `PARAMS`, `INCIDENT` (un `IncidentText`), `VERBS`, `CAUSES`, `STAGES`
     (`StageText`), `GOALS` (`GoalText`), `LEGEND`, `STRINGS` (el resto, con `{marcadores}`)
     y `LESSON` (con enlaces que hayas comprobado);
   - `scenario.py`: `stream(variant, seed=s, **params)` produce minuto tras minuto de una
     ejecución sin fin: `{"start": a, "end": b, "incidents": [(t0, t1, kind, severity,
     clave_de_causa)], "tables": {nombre: [tuplas]}}`, las filas que empezaron en [a, b),
     con tiempos e ids absolutos. Usa `core.vtime.VirtualRun`, `core.services` o `core.net`,
     y `core.incidents.schedule` (incidentes al azar con un primero fijo);
   - `lab.py`: `META` (`id`, `params`: `{nombre: Param(por_defecto)}`), los números y
     `stage_of`;
   - `test_lab.py`: el comportamiento dado pasa; los tests de tu código usan
     `@your_code(etapa, …)`; compara índices de etapa (`world.stage_index(v)`), nunca
     palabras, para que pasen en cualquier idioma. Un test que muestra lo que hace mal el
     `main.py` inicial lleva `@starting_code`: cuando cambias `main.py`, su fallo pasa a ser
     un salto (skip), no un test en rojo.
2. **Un World** en `live/worlds/<lab>.py` (exportado como `WORLD`) con los ganchos de la
   tabla del [README en inglés](README.md#adding-a-lab). Sus palabras salen del catálogo:
   `self.s("clave", ...)` (STRINGS), `self.word(clave)` (VERBS), `self.cause(inc)` (CAUSES),
   `self.screen` (las palabras de la pantalla).
3. **Un adaptador por dibujo** en `live/adapters/<lab>.py` (se importan todos los módulos de
   esa carpeta). Un laboratorio puede tener varios: cada `@adapts(lab, view)` añade un dibujo
   al que el visor cambia con `v`; `World.view` es el que abre primero (`"lanes"` salvo que
   digas otra cosa). Las palabras del dibujo vienen de `self.world.screen.STATES` o de los
   `STRINGS` del laboratorio. Los nodos de un laboratorio distribuido son subclases de
   `core.net.Node` con manejadores `on_<tipo>`; copia `labs/broadcast` para empezar uno.
4. **Una View** en `live/views/` solo para un tipo de dibujo nuevo: hereda de `View`, pon
   `name`, implementa `draw(cv, adapter, variant, t)` y decórala con `@register`.

## Rendimiento

Tras 7 minutos, un fotograma de 110x44 se dibuja en 2–4 ms; añadir un minuto tarda de 10 ms
(retry_storm) a 30 ms (caching). Simular un minuto tarda 0,1–1,3 s en el proceso hijo, muy por
delante del cabezal.

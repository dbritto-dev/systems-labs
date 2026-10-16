# Laboratorio: despliegues canario

*[Read in English](../README.md)*

Los usuarios envían ~200 peticiones/s a cuatro rutas (`/home` 55%, `/search` 25%, `/cart` 15%,
`/pay` 5%). Un **enrutador** las reparte entre 20 instancias que corren la **versión activa** (~0.3%
de errores, p99 ~160 ms). Cada par de minutos el equipo publica una versión nueva: un **despliegue**.
Tú escribes el controlador de despliegues.

Para cada despliegue el escenario crea un `Release()` y llama a `release.decide(metrics)` enseguida y
luego cada 5 s; devuelves la parte del tráfico que recibe la versión nueva (de 0 a 1). El enrutador
manda esa parte de las peticiones, al azar, a la versión nueva (el **canario**) y el resto a la versión
activa (la **base**). `1.0` deja la versión nueva activa en todas partes; `0.0` la revierte. Las
métricas cuentan las peticiones, los errores y las respuestas lentas (> 250 ms) de cada versión desde
que el enrutador cambió el reparto por última vez, en total y por ruta, así que el canario y la base
siempre se comparan en los mismos segundos.

La mayoría de las versiones son buenas. Algunas son malas, cada una a su manera, como en producción:
**caídas en bucle** (falla el 50-80% de sus peticiones enseguida: falta un ajuste en producción, una
errata en la configuración, se queda sin memoria al arrancar), una **regresión de errores** (el 0.3% de
errores pasa a ~3%: un caso límite sin tratar, un timeout demasiado corto), una **versión lenta** (una
consulta N+1 nueva, registros síncronos, un fallo en la clave de caché: +150-250 ms en un cuarto de
las peticiones, y ningún error), o un **fallo solo en /pay** (un cambio de redondeo, el lector de
cupones: falla el 15-30% de los pagos, el 5% del tráfico). Y a veces sale una versión buena mientras
una **dependencia falla a ratos** (la base de datos conmuta, un fallo de DNS, un proveedor de pagos
lento): los errores (10-20%, a ráfagas) y las respuestas lentas suben en las dos versiones. Una versión
mala que llega al 100% sigue activa hasta que alguien de guardia la revierte a mano, 2 minutos después
del despliegue. El primer despliegue es siempre una **versión lenta a la 0:20**. La ejecución nunca se
reinicia.

```
uv run python -m live canary_releases --lang es            # míralo; edita es/main.py y guarda
uv run python -m live canary_releases --lang es --lesson   # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/canary_releases            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves (el primer despliegue, la versión lenta) |
|---|---|---|
| 0 Todo a la vez (dada) | `decide` devuelve 1.0 | le llega a cada usuario: el 25% de todas las peticiones dañadas durante 2 minutos (p99 ~330 ms en vez de ~160 ms), hasta la vuelta atrás a mano |
| 1 Canario fijo | `fixed_canary(m)`: 5%, revierte por encima del 5% de errores, a todas partes tras 60 s | un hilo morado a una instancia; sin errores, a los 60 s se activa: 11-12% dañadas. Revierte unas caídas en bucle en 5 s, pero deja activarse la mayoría de las regresiones de errores (9 de 14) y de los fallos en /pay (18 de 19), y revierte 24 de 25 versiones buenas publicadas con una dependencia inestable |
| 2 Canario por etapas | `z_score`, `worse(canary, baseline)`, `ramp(m)`: errores y lentas frente a la base, en total y por ruta, al menos 5 respuestas malas y z > 4, etapas 5% → 25% → 50% → 100% de 20 s y 200 muestras | la versión lenta se revierte desde el 5% a los 5 s (0.04-0.1% dañadas); las buenas llegan al 100% en ~65 s, con o sin dependencia inestable; cada versión mala se revierte (el fallo en /pay al 25%) |

Objetivos, por despliegue: base correcta (≤ 1% de errores antes de desplegar), dañadas ≤ 0.5%
(peticiones que la versión nueva hizo fallar o ralentizó, sobre todas las peticiones de la ventana de 2
minutos del despliegue), versiones malas al 100% = 0, falsas alarmas = 0 (versiones buenas revertidas)
y despliegue ≤ 90 s (desde desplegar hasta el 100%, solo las buenas). La etapa se juzga con el primer
despliegue: un enrutador que nunca repartió el tráfico es la etapa 0; un canario que falló un objetivo
es la etapa 1.

Por qué importa cada parte de la etapa 2 (medido con 20 semillas, 20 minutos cada una): comparar solo
errores deja pasar cada versión lenta; comparar solo el total deja llegar al 100% 4 de 19 fallos en
/pay (diluidos: +1.5% de errores en el total); un listón de 3 errores estándar en vez de 4 revierte 4 de
25 versiones buenas publicadas con una dependencia inestable (10 pruebas cada 5 s lo cruzan por azar);
y sin un mínimo (culpar por una sola respuesta mala) se revierten 6 de 15 versiones buenas normales.

**Los dibujos.** La ventana abre en los carriles: usuarios (naranjas cuanto más esperan: una versión
lenta se ve aquí) → el enrutador (la puerta: punteada en morado mientras reparte el tráfico, cerrada
en rojo mientras fallan muchas peticiones) → la flota como un solo servidor, su indicador la parte de
la versión nueva (morado) o lleno en azul cuando todos están en la versión activa, su borde rojo
mientras una versión daña peticiones; las peticiones al canario son los puntos morados grandes.
Debajo: `ACTIVA v100`, `CANARIO v102 25%`, `REVERTIDA v101` o `VERSIÓN MALA ACTIVA`. Pulsa `v` (o
`--view cluster`) para ver las instancias: azules con la versión activa, moradas con el canario
(tantas como su parte: 1 de 20 al 5%), rojas mientras su versión hace fallar peticiones, naranjas
mientras las ralentiza; las peticiones vuelan a la instancia que las recibió. La gráfica muestra las
peticiones de cada segundo según la versión que respondió (azul la activa, morado el canario), con las
lentas en naranja y las fallidas en rojo encima. Durante un despliegue el titular compara la versión
activa con el canario: `errores 0.3%→3.1% · lentas 0.2%→0.1%`.

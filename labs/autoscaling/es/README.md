# Laboratorio: autoescalado

*[Read in English](../README.md)*

Los usuarios envían ~120-230 peticiones/s: el tráfico sigue un **día** comprimido (mucho a la
1:00, poco a las 6:00, un "día" cada 10 minutos), deriva y llega a ráfagas cortas. Un
balanceador de carga lo reparte entre una **flota de instancias**; una instancia caliente hace
~20 peticiones/s (2 a la vez, ~100 ms cada una) y pone en cola el resto, y un usuario cuya
petición espera 2 s se rinde (un 504).

Cada 10 s el escenario llama a tu `Autoscaler.desired(metrics)` con las métricas de los últimos
10 s (`rps`, `cpu`, `in_flight`, cuántas instancias tienes, cuántas están arrancando
(`booting`) o calentándose (`warming`)) y arranca o termina instancias hasta llegar al número
que devuelves (de 2 a 40). Una instancia nueva **arranca durante 20-35 s** (la pagas, no sirve
nada) y luego **se calienta**: 2x más lenta al principio (cachés vacías, el JIT en frío),
caliente a los 20 s. El **costo** son instancias-segundo, contando las que arrancan.

De vez en cuando, como en producción: el tráfico da un **pico** de 1.5-1.9x en un minuto (un
anuncio en la tele, un correo de marketing, una publicación viral, una venta relámpago),
**baja** al 40-60% (el tráfico se traslada a otra región, una caída aguas arriba, una versión
rota de la aplicación móvil), la **CPU se vuelve ruidosa** (un proceso por lotes, una copia de
seguridad o un enviador de registros en las mismas máquinas: la CPU marca +30-50%, la capacidad
no cambia) o una **ola de arranques en frío** reinicia las instancias lote a lote (un
despliegue gradual, un cambio de configuración, una rotación de máquinas: cada una vuelve a
estar fría). El primer incidente es siempre un **pico de 2x entre 0:20 y 2:00**. La flota a la
0:00 se dimensionó a mano para la mañana (ocupada al 65%). La ejecución nunca se reinicia.

```
uv run python -m live autoscaling --lang es            # míralo; edita es/main.py y guarda
uv run python -m live autoscaling --lang es --lesson   # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/autoscaling            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves (el primer pico) |
|---|---|---|
| 0 Flota fija (dada) | `desired` devuelve la flota que tienes | el pico la satura: 45-75% servidas, p99 2 s (timeouts), al final 8-35% menos capacidad que tráfico; a las 6:00 más del 60% está ociosa |
| 1 Umbrales de CPU | `cpu_step(cpu, instances)`: +1 con la CPU sobre 70%, -1 bajo 30% | una instancia naranja claro por turno, siempre por detrás: p99 0.4-2 s, hasta un 14% de timeouts, margen de -3% a +31% al final. Más tarde, un proceso por lotes ruidoso añade instancias para nada (costo +86-102%) |
| 2 Seguimiento de objetivo | `target_tracking(m)`: `ceil(rps / TARGET_RPS)`; `stabilised(t, want)`: reduce solo tras 40 s | arrancan lotes enteros a la vez: 100% servidas, p99 ~0.3 s, margen +71-103%, 0 oscilaciones, costo +15-19% |

Objetivos, por incidente: base correcta (antes), ≥ 99% servidas y p99 < 1 s (durante), margen
≥ 50% en los últimos 20 s del incidente (capacidad de sobra sobre el tráfico; el objetivo es
100%, porque `TARGET_RPS` es la mitad de lo que puede una instancia), oscilaciones ≤ 2
(instancias añadidas y quitadas otra vez en 30 s, desde el inicio del incidente hasta 60 s
después) y costo ≤ ideal +50% (instancias-segundo frente a una flota que sigue al tráfico
exactamente a `TARGET_RPS`, en el mismo tramo). La etapa se juzga con el primer pico: una flota
que nunca creció es la etapa 0; una que creció pero falló un objetivo, la etapa 1.

Por qué importan las dos partes de la etapa 2: sin contar el calentamiento
(`m.instances + necesarias - m.serving`) cada turno vuelve a pedir las instancias que aún
arrancan, y el mismo pico cuesta +31-43% en vez de +15-19%. Sin la ventana de estabilización
cada ráfaga añade instancias y el bajón siguiente las quita: 2-7 oscilaciones en el primer
pico, frente a 0.

**Los dibujos.** La ventana se abre con los carriles: usuarios → el balanceador de carga (la
puerta: cerrada en rojo mientras hay timeouts) → la flota como un solo servidor, cuyo indicador
es el número de instancias de 40 (naranja claro mientras alguna arranca, morado mientras alguna
se calienta) y cuyo borde se pone rojo mientras tiene menos capacidad que tráfico; debajo, su
estado y las instancias que sirven + las que arrancan. Pulsa `v` (o `--view cluster`) para ver
la flota en sí: un nodo por hueco de instancia, tenue si está vacío, naranja claro mientras
arranca, morado mientras se calienta, azul cuando está caliente, rojo mientras crece su cola;
las peticiones vuelan a la instancia que las recibió. La gráfica muestra la flota en cada
segundo con los mismos colores, y en rojo las instancias que le faltan para el objetivo.

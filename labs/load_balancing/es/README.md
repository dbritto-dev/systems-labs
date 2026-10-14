# Laboratorio: balanceo de carga

*[Read in English](../README.md)*

Los usuarios envían ~250 peticiones/s (que varían despacio). Cada petición llega a uno de
**4 balanceadores de carga**, y el `Balancer.pick()` de ese balanceador elige uno de **8
servidores**. Un servidor atiende 4 peticiones a la vez (~40 ms cada una) y pone en cola el
resto; una petición sin respuesta en **1 s** da timeout (un 504), y el servidor, que no se
entera, sigue trabajando en ella. Un balanceador solo conoce la carga de los servidores por
un **informe de carga**: cada 0.5 s, cada balanceador en su momento, lee cuántas peticiones
tuvo en curso cada servidor, de media, en el medio segundo anterior. Entre informes, lo que
ve son datos viejos.

De vez en cuando, como en producción, un servidor **se vuelve lento** 3.5-5x (un vecino
ruidoso, una tormenta de GC, un disco que falla, una zona de disponibilidad degradada) o
**se reemplaza por uno en frío** que empieza 5-9x más lento y se va calentando (el
autoescalado, una instancia spot reclamada, un despliegue gradual). El primer incidente es
siempre el servidor s2 yendo 5x más lento entre 0:20 y 0:32. La ejecución nunca se
reinicia: las colas, los informes de carga y el reloj siguen.

```
uv run python -m live load_balancing --lang es            # míralo; edita es/main.py y guarda
uv run python -m live load_balancing --lang es --lesson   # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/load_balancing            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Por turnos (dada) | el siguiente servidor en su turno | el servidor lento recibe su 12.5% entero; su cola crece y ~11% de todas las peticiones dan timeout |
| 1 Menos pendientes | `least_outstanding(loads)`: el servidor con menos en curso | el lento recibe ~6%, pero cada balanceador va en manada: durante medio segundo lo manda todo al único servidor que parecía libre, y si es el lento la ráfaga da timeout (p99 ~1 s, 1-2% de timeouts) |
| 2 Dos opciones al azar | `two_choices(loads, rng)`: el menos cargado de dos servidores al azar | el lento recibe ~5%, sin manadas, sin timeouts, p99 ~0.5 s |

Objetivos, por incidente: base correcta (antes), la parte de peticiones del servidor lento
≤ 10% (durante; el reparto justo es 12.5%), latencia p99 < 750 ms (durante), ≥ 99% servidas
sin timeout (durante), ≥ 95% de las peticiones que empiezan en los 5 s siguientes servidas en
menos de 750 ms (después).

Por qué dos opciones al azar ganan al menos cargado: con datos frescos el menos cargado es lo
mejor, pero con datos viejos todos los balanceadores coinciden en el mismo "mejor" servidor
hasta el siguiente informe, y se lo mandan todo. Dos opciones al azar nunca eligen el
servidor más ocupado, y aun así reparten el resto del tráfico entre todos los que no lo
están. Prueba con tres opciones: vuelven a ir un poco en manada.

**Los dibujos.** La ventana se abre con el clúster: los 4 balanceadores en la fila de arriba,
los 8 servidores debajo (azules, y naranjas a medida que crece su cola; el lento, morado), y
cada petición volando de los usuarios a un balanceador y de ahí al servidor que eligió. Un
balanceador que va en manada se pone naranja; los timeouts mueren en rojo. Pulsa `v` (o
`--view lanes`) para ver lo que ven los usuarios: usuarios → los balanceadores (la puerta:
naranja mientras uno va en manada, cerrada en rojo mientras hay timeouts) → la flota, cuyo
indicador es la cola del servidor más ocupado.

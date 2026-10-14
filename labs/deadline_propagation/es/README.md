# Laboratorio: propagación del plazo

*[Read in English](../README.md)*

Una petición pasa por una cadena de cuatro servicios: gateway → api → orders → db (pasarela,
api, pedidos y base de datos). Los usuarios envían ~40 peticiones/s y se rinden a los 2 s.
Cada servicio ejecuta tu `handle`: su propio trabajo (unos ms; en la base de datos, la
consulta) mientras ocupa uno de sus trabajadores, y luego una llamada al siguiente
servicio, ocupando el trabajador mientras espera. Una llamada es una petición de red:
cuando quien llama deja de esperar, el llamado no lo sabe y sigue adelante.

En momentos al azar, como en producción, la base de datos se vuelve lenta: de 120 a 160 ms
por consulta en vez de 15 (un plan de consulta lento, contención de bloqueos, una réplica
degradada, una tormenta de GC, una tarea de mantenimiento, una caché en frío tras una
conmutación por error). Con 3 conexiones responde entonces ~20 consultas/s, la mitad de lo
que piden los usuarios, y se forma una cola delante de ella. El primer incidente siempre
es entre 0:20 y 0:30, 150 ms por consulta.

```
uv run python -m live deadline_propagation --lang es            # míralo; edita es/main.py y guarda
uv run python -m live deadline_propagation --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/deadline_propagation            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves (primer incidente, 12 semillas) |
|---|---|---|
| 0 Timeouts por salto (dada) | cada salto espera su propio `HOP_TIMEOUT` (2 s) desde su propia llamada | quien llama sigue esperando cuando el usuario ya se fue (exceso p99 de 25 ms a 1.5 s); del 31 al 51% del trabajo es para usuarios que se fueron; servidas del 28 al 58% de lo que podía la base de datos |
| 1 Plazo propagado | envía `next_deadline(deadline)` (tu plazo menos `MARGIN`) y espera hasta tu propio plazo | exceso 0, pero la base de datos aún ejecuta consultas en cola de usuarios que se fueron (derroche del 38 al 57%), así que las servidas se quedan entre el 20 y el 47% |
| 2 Plazo + saltar lo tardío | `if expired(...)`: lanza `DeadlineExceeded` antes del trabajo y antes de la siguiente llamada | nada de derroche; la cola se vacía al instante y la base de datos sirve del 97 al 100% de lo que puede |

Objetivos, evaluados en cada lentitud: base correcta (servidas ≥ 99%, antes); derroche ≤ 5%
(la parte del trabajo propio de los servicios hecha cuando su usuario ya se había ido, para
peticiones que llegan a un servicio desde el inicio de la lentitud hasta 3 s después;
durante); servidas ≥ 80% del máximo posible (peticiones servidas frente a las que podía
responder la base de datos lenta, o las que pidieron los usuarios si eran menos; durante);
exceso p99 < 10 ms (cuánto siguió esperando quien llama después de que su usuario se fue;
durante).

**Dibujo de carriles** (el de inicio). Los usuarios esperan a la izquierda, ante la puerta
de la pasarela: en blanco, en naranja pasado 1 s. Un usuario que se rindió mientras la
cadena aún trabaja en su petición se vuelve un anillo rojo. La caja del servidor es la
cadena; su indicador son las conexiones ocupadas de la base de datos, en rojo mientras
ejecutan consultas de usuarios que se fueron. Las barras muestran dónde están ahora las
peticiones en cada servicio: trabajando (blanco), en cola (naranja), para usuarios que se
fueron (rojo). La gráfica muestra las consultas por segundo a la base de datos: en blanco
las de usuarios que aún esperan, en rojo las de usuarios que ya se habían ido.

**Dibujo de clúster.** Pulsa `v` (o `--view cluster`) para ver la cadena como cuatro nodos
(pasarela y api arriba; pedidos y base de datos abajo, se lee como una Z). Las peticiones
llegan desde los clientes; las llamadas vuelan de cada servicio al siguiente y esperan
junto al llamado. Una llamada cuyo usuario ya se fue es roja: trabajo y espera para nadie.
Las llamadas cortadas por un timeout o que fallan mueren en rojo en su arista; un nodo se
vuelve rojo mientras la mayor parte de su trabajo es para usuarios que se fueron.

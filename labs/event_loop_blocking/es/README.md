# Laboratorio: bucle de eventos bloqueado

*[Read in English](../README.md)*

Un servicio web asyncio atiende ~100 peticiones/s con **un solo bucle de eventos**. El 82% de las
peticiones son ligeras (leer, una consulta async a la BD, componer la respuesta: ~10 ms). El resto
hace una **llamada bloqueante** cada una: un driver síncrono de BD (8%, ~10 ms), un cliente HTTP
síncrono hacia la API de un socio (4%, ~30 ms), **redimensionar** la imagen de una subida (4%, ~40 ms
de CPU) o el **json.dumps** enorme de exportar un informe (2%, ~30 ms de CPU). Cada manejador pasa su
llamada bloqueante por tu `Service.run_blocking(call)`, que hoy solo hace `call()` en el hilo del
bucle: durante esos milisegundos **no corre nada más**, ni otra petición, ni un temporizador, ni el
chequeo de salud. Un usuario se rinde a los 5 s (un 504; el manejador sigue igualmente). El
balanceador chequea `/health` cada 2 s con un timeout de 1 s; tras **3 fallos seguidos el orquestador
mata el proceso**, y uno nuevo tarda 10 s en arrancar (mientras, 503, y se pierde todo lo que tenía).

De vez en cuando, como en producción: un **lote de fotos** hace lento el redimensionado (una
fotógrafa de bodas, la importación de un catálogo, la sincronización de carretes: 4.6-6 núcleos de
redimensionar), una **dependencia síncrona va lenta** (un bloqueo en la base de datos, la API de un
socio degradada, un resolvedor DNS lento: llamadas síncronas 30-80 veces más lentas), una **ráfaga de
informes** (cierre de mes, un panel que se refresca en cada pestaña: 4.5-6 núcleos de json.dumps) o
**pausas de recolección de basura** paran el proceso 18-36 ms, una y otra vez (rellenar una caché,
una fuga, una cuota de CPU). El primer incidente es siempre un **lote de fotos entre 0:20 y 0:50**.
La ejecución nunca se reinicia.

La máquina tiene 4 núcleos. En este laboratorio los hilos están simulados, con un **GIL**: un hilo
que espera E/S lo suelta, pero la CPU en hilos corre de llamada en llamada, y el propio bucle va 2x
más lento mientras un hilo calcula. Los procesos tienen su propio GIL; mandar una llamada a uno cuesta
1 ms de serializar (pickle) en el bucle. Mira `api.py`.

```
uv run python -m live event_loop_blocking --lang es            # míralo; edita es/main.py y guarda
uv run python -m live event_loop_blocking --lang es --lesson   # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/event_loop_blocking            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves (el primer lote de fotos) |
|---|---|---|
| 0 Llamadas síncronas en el bucle (dada) | `run_blocking` hace `call()` | ya antes: retardo p99 del bucle 60-90 ms, peticiones ligeras p99 135-180 ms. Durante el lote cada redimensionado retiene el bucle ~400 ms: retardo p99 de 1-4 s, fallan 13-14 chequeos, matan el proceso (dos veces), se sirve el 6-9% de las peticiones pesadas |
| 1 Delegado a hilos | `await to_thread(call)` | el bucle queda libre (retardo ~1 ms, ningún chequeo falla, ligeras p99 12 ms), pero 8 hilos comparten un GIL: 565-684 llamadas en cola, solo el 3-4% de las pesadas a tiempo, y la cola tarda minutos en vaciarse después |
| 2 Ejecutores acotados | CPU a un `ProcessPool(4)`, E/S a un `ThreadPool(16)`, cada cola acotada (8 y 32: `Overloaded` → 503), y un vigilante del retardo | retardo <1 ms, ligeras p99 11 ms, 86-91% de las pesadas servidas (el resto recibe un 503 al instante), como mucho 8 en cola, retardo publicado cada segundo |

Objetivos, juzgados por incidente (durante él): retardo p99 del bucle < 50 ms (medido desde fuera de tu
código, cada 50 ms), chequeos de salud fallidos = 0, peticiones ligeras p99 < 100 ms (una fallida
cuenta como 5 s), peticiones pesadas servidas a tiempo ≥ 70%, llamadas en cola en los ejecutores ≤ 50,
y publicaciones de tu vigilante en ≥ 90% de los segundos. La etapa se juzga con el primer lote de
fotos: un bucle parado (retardo o chequeos) es la etapa 0; un bucle libre que falla otro objetivo es
la etapa 1.

Por qué importa cada parte de la etapa 2 (el primer lote): con los grupos correctos pero sin límite
de cola, la cola de CPU llega a 67-121 llamadas y solo se sirve a tiempo el 61-85% de las pesadas;
con colas acotadas pero la CPU en hilos (un grupo para todo), el GIL sirve solo el 45-50%; sin el
vigilante nadie ve el retardo (0% publicado). Los otros incidentes enseñan el resto: una dependencia
lenta llena el grupo de E/S, no el de CPU (compartimentos estancos); las pausas de basura son retardo
que ninguna delegación quita, y solo el vigilante lo muestra (10-26 ms de p99 con la solución).

**Los dibujos.** La ventana se abre en los carriles: usuarios → el socket del proceso (la puerta:
cerrada en rojo mientras matan y reinician el proceso) → el bucle de eventos como servidor, su
indicador cuánto del último segundo estuvo retenido el bucle (verde azulado para E/S bloqueante,
naranja para CPU, rosa para el GIL, morado para la basura), su borde rojo mientras el bucle va con
retraso; debajo, su estado y retardo, `BLOQUEO 420ms` contando durante una parada, u `OCUPADO +663`
cuando las llamadas se amontonan en los ejecutores. Pulsa `v` (o `--view cluster`) para ver el
proceso: el bucle es el primer nodo (verde, rojo mientras está bloqueado, oscuro si lo matan), y luego
cada trabajador de cada grupo, apagado si está libre, verde azulado con E/S, naranja con CPU, rosa
mientras tiene una llamada pero espera al GIL (un hilo) o a un núcleo (un proceso); las peticiones
vuelan hacia el bucle, y las llamadas del bucle al trabajador que las ejecuta. Debajo: ocupados/tamaño
+en cola de cada grupo. La gráfica muestra el peor retardo del bucle en cada segundo, del color de lo
que lo retuvo.

# Laboratorio: replicación en cadena

*[Read in English](../README.md)*

Un almacén clave/valor guardado en 4 nodos (`n0`..`n3`) en una red simulada (~30 ms por mensaje). Un
maestro de configuración (supón que es fiable, como ZooKeeper o etcd) guarda la cadena, la cabeza
primero, y le manda a cada nodo la cadena nueva cuando cambia. Los clientes mandan ~10 escrituras por
segundo a la cabeza y ~10 lecturas por segundo al nodo que elige `read_from(chain, rng)`.

Los incidentes llegan al azar, como en producción: se cae la cabeza, la cola o un nodo en medio (un
kernel panic, el kernel lo mata por memoria, se rompe un disco…; el maestro lo saca de la cadena
cuando expira su sesión, 1 s después), o un nodo se vuelve lento y atasca la cadena (pausas del
recolector de basura, un disco lleno, un vecino ruidoso; el maestro lo expulsa a los 2 s y lo aísla,
así que arranca de nuevo vacío). Cuando acaba el incidente el nodo vuelve vacío y entra otra vez: el
maestro le pide que copie el estado de la cola (la copia tarda ~1 s en la red) y luego lo añade como
la cola nueva. La ejecución nunca se reinicia. El primer incidente siempre tumba el nodo del medio
`n1` a las 0:20; vuelve a las 0:30.

```
uv run python -m live chain_replication --lang es            # míralo; edita es/main.py y guarda
uv run python -m live chain_replication --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/chain_replication            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves (primer incidente) |
|---|---|---|
| 0 Primario-respaldo (dada) | la cabeza aplica una escritura, responde enseguida y la envía a los respaldos cada 0,5 s; las lecturas van a cualquier réplica | lecturas viejas aunque nada falle (de 3 a 7 en la ventana del primer incidente); más tarde, una caída de la cabeza pierde escrituras confirmadas |
| 1 Cadena | `on_put` numera la escritura, `on_write` aplica en orden de seq, `apply` la pasa (o, en la cola, responde y confirma), `on_ack` olvida; `read_from` devuelve la cola | nada viejo, nada perdido; cuando cae `n1` la cabeza sigue enviando a `n2`, que espera para siempre las escrituras que `n1` se llevó: ninguna escritura vuelve a salir bien (15 s sin escribir) |
| 2 Cadena + reparación | `chain_changed`: una cabeza nueva descarta su hueco, una cola nueva responde lo que envió, un nodo con sucesor nuevo reenvía lo enviado y no confirmado; la cola guarda lo que aplica mientras un nodo la copia | `n0` reenvía a `n2` y las escrituras atascadas tras `n1` terminan (~1,2 s, ninguna falla); `n1` copia la cola y entra como cola; todas las metas OK |

Metas, juzgadas por incidente: lecturas viejas = 0 (desde 15 s antes hasta que el nodo vuelve),
pérdidas = 0 (escrituras confirmadas que no tiene ningún nodo vivo de la cadena, hasta 5 s después),
sin escribir ≤ 3 s (segundos en los que salió bien menos del 90% de las escrituras, desde su inicio
hasta 5 s después), al día = 4 (réplicas en la cadena, vivas, con cada escritura confirmada hace más
de un segundo, 5 s después) y p99 de escritura ≤ 500 ms (los 15 s de antes).

Una lectura es *vieja* cuando devuelve un valor más antiguo que una escritura confirmada antes de
que empezara, o que una lectura que terminó antes de que empezara (un valor que alguien vio no puede
desaparecer). El verificador lee el `self.store` de cada nodo cada 250 ms, fuera de la red.

- **Por qué la cola.** Una escritura se confirma solo cuando la tiene la cola, y pasó por cada nodo
  por el camino: así cada nodo tiene cada escritura confirmada, y la cola no tiene nada que no esté
  en todos. Una lectura de la cola siempre está al día y nunca ve un valor que se pueda perder. Lee de
  la cabeza y verás escrituras que aún pueden morir con ella.
- **Por qué guardar lo enviado.** Cada reparación es la misma idea: el nodo antes del hueco aún tiene
  las escrituras que pasó hasta que vuelve la confirmación de la cola, así que puede enviarlas otra
  vez. Así entra también un nodo: copia la cola, y la cola guarda (y luego reenvía) lo que aplicó
  mientras tanto.
- **El precio.** Cada escritura cruza todos los nodos: la latencia es la suma de los saltos (~160 ms
  aquí), y un nodo lento frena cada escritura hasta que el maestro lo expulsa (la gráfica se pone
  naranja).
- Variantes que usan las pruebas: una cadena que lee de cualquier nodo cae en la etapa 0 (una lectura
  ve una escritura que el nodo caído se lleva, y una lectura posterior no la ve); una reparación cuya
  cola olvida lo que aplica durante una copia, o una cabeza que espera la confirmación de cada
  escritura antes de mandar la siguiente, caen en la etapa 1.

Cómo habla tu nodo está en `core/net.py`: `self.reply`, `self.send`, `await self.rpc`,
`self.every`, `self.spawn`, `self.now()`, y manejadores `on_<tipo>`.

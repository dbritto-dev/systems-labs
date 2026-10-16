# Laboratorio: consumidores de una cola de mensajes

*[Read in English](../README.md)*

Los productores envían ~40 trabajos por segundo a una cola como Amazon SQS. Siete procesos
worker los reciben, seis a la vez cada uno, y llaman a tu `Consumer.process(msg)`. Un mensaje
recibido queda oculto para los demás workers durante su timeout de visibilidad (2 s); si no se
borra (se confirma) antes, la cola se lo da a otro worker. Un trabajo tarda ~0,1 s. En momentos
al azar, como en producción, los procesos worker caen a mitad de trabajo y vuelven 2 s después
(un despliegue, un OOM, instancias spot que se recuperan), un servicio de abajo se vuelve lento y
el 10% de los trabajos tarda 2,5–5 s (más que el timeout de visibilidad), un despliegue malo de
un productor envía mensajes veneno que fallan siempre (cada intento espera 2,5 s y falla), o el
servicio de abajo tiene una caída breve (cada llamada falla durante 1–3 s). La ejecución nunca
se reinicia. El primer incidente siempre es un lote de veneno entre 0:20 y 0:30.

```
uv run python -m live message_queue_consumers --lang es            # míralo; edita es/main.py y guarda
uv run python -m live message_queue_consumers --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/message_queue_consumers            # x = aún no, X = hecho
```

Dos dibujos (`v` cambia): **clúster** (abre con este) muestra la cola (izquierda), los siete
procesos worker a su alrededor y la cola de mensajes muertos (derecha) como nodos: las
entregas vuelan a los workers, las confirmaciones vuelven (verde), los mensajes apartados vuelan
a la DLQ (morado), los trabajos perdidos mueren en rojo, y un proceso caído se pone rojo.
**carriles** muestra cada mensaje de la cola como un círculo, la cola como la puerta y el grupo
de workers como el servidor, con su indicador la parte de puestos ocupados.

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Confirma al recibir (dada) | `delete`, luego `handle` | las caídas, los trabajos que fallan y el veneno pierden trabajos (rojo); la DLQ sigue vacía |
| 1 Confirma al terminar | arranca `heartbeat` como tarea, `handle`, luego `delete`; cancela el latido en `finally`; un trabajo que falla solo devuelve | nada perdido, los trabajos lentos no se dan a un segundo worker; pero el veneno vuelve para siempre: el mensaje más viejo es cada vez más viejo, y tras unas pocos lotes de veneno los workers están ocupados con él y la cola se atasca |
| 2 Reintentos + DLQ | con `JobFailed`, `on_failure`: ocúltalo `backoff(receive_count)` (1, 2, 4 s… con jitter), y tras `MAX_RECEIVES` entregas `dlq.send` y `delete` | el veneno se aparta tras 4 intentos (morado), una caída breve no aparta nada; todos los objetivos OK |

Objetivos, evaluados en cada incidente: base correcta (antes), perdidos = 0, duplicados ≤ 1%
(trabajos que hacen dos workers a la vez, o que se repiten después de hechos), edad en cola
p99 < 1 s (cuánto espera un mensaje antes de que un worker lo tome por primera vez), todos para
los trabajos enviados durante el incidente y los 5 s siguientes; y "DLQ: solo veneno": todo el
veneno apartado, y ningún trabajo bueno apartado (después; "nada" cuando no hubo veneno).

- **Por qué el latido.** Confirmar al terminar, sin más, hace que un trabajo más lento que el
  timeout de visibilidad vuelva mientras su primer worker sigue con él: un segundo worker lo
  empieza también (la casilla Dobles). Subir el timeout para todos los mensajes también
  funcionaría, pero entonces los mensajes de un worker caído tardan eso en volver. Un latido
  mantiene el timeout corto y los trabajos lentos ocultos.
- **Por qué backoff, y por qué limitado.** Sin límite, un mensaje veneno se reintenta para
  siempre. Sin backoff, el límite también aparta trabajos buenos: cuando el servicio de abajo
  cae un segundo, cuatro intentos en 0,3 s fallan todos y un trabajo bueno acaba en la DLQ. El
  backoff reparte los intentos más allá de la caída.
- **Los duplicados siguen pasando.** Un worker que cae después del trabajo y antes de confirmar
  deja un trabajo que se ejecutará otra vez. «Al menos una vez» quiere decir que los propios
  trabajos deben ser idempotentes.

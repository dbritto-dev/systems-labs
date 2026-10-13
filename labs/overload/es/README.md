# Laboratorio: sobrecarga y colas

*[Read in English](../README.md)*

Un servidor atiende una cola a 100 peticiones/s (10 ms cada una). Los usuarios envían
~75 peticiones/s (que varían despacio). Un usuario espera 1 s una respuesta; luego se rinde
con ese intento y lo vuelve a enviar (como mucho 2 reintentos). El intento abandonado sigue
en la cola. Un rechazo es una respuesta: no hay reintento.

Los incidentes llegan al azar, como en producción: **picos de tráfico** (2–3x durante
5–15 s: una publicación viral, una estampida tras un despliegue…) y **bajas de capacidad**
(el servidor va al 30–50%: un nodo perdido, un vecino ruidoso…). El primer incidente
siempre es un pico de 2.5x entre 0:20 y 0:30. La ejecución nunca se reinicia, así que una
cola rota sigue rota.

```
uv run python -m live overload --lang es            # míralo; edita es/main.py y guarda
uv run python -m live overload --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/overload            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` (`Policy`) | Lo que ves |
|---|---|---|
| 0 FIFO sin límite (dada) | admite todo, lo más antiguo primero | la cola crece a miles; el servidor trabaja para quien ya se fue (DERROCHA); nunca se recupera, ni siquiera tras el pico |
| 1 Cola con límite | `admit`: rechaza cuando la cola tiene `MAX_QUEUE` | la puerta rechaza, la cola se queda en 200, pero el trabajo sigue siendo para quien se fue |
| 2 Salta lo tardío | `drop`: `too_late(request, now)` (queda menos de 0.1 s) | no se desperdicia trabajo, vuelve el goodput, se recupera en segundos, pero las respuestas tardan ~0.9 s |
| 3 LIFO adaptativo | `newest_first`: `overloaded(queue_len)` (cola > 20) | respuestas en ~20 ms incluso con 2.5x el tráfico |

Objetivos, evaluados en cada incidente: base correcta (antes); la cola se queda en ≤ 250
(durante); pérdida < 5% del trabajo (durante y 5 s después); goodput ≥ 80% de lo posible
(la capacidad del servidor, o lo que pidieron los usuarios si es menos) (durante); mediana
de respuesta < 300 ms (durante); recuperado en 5 s (después: 3 s seguidos con ≥ 90% de los
primeros intentos respondidos a tiempo).

Por qué saltar usa un margen: una petición sacada del principio de una cola FIFO llena tiene
casi exactamente la edad del timeout, así que la respuesta llegaría justo después de que el
usuario se rindiera. `too_late` la salta cuando queda menos de `MARGIN` (0.1 s): el plazo
viaja con la petición, como con los plazos de gRPC.

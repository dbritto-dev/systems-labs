# Laboratorio: claves de idempotencia

*[Read in English](../README.md)*

Los clientes pagan ~40 veces por segundo a través de tu `PaymentService.charge(key, account,
amount)`. Cada pago lleva una clave de idempotencia. Un cliente espera hasta 1 s una
respuesta; si no llega, reintenta con la misma clave (hasta 4 intentos, esperando cada vez
más), y después de un 409 (`Conflict`) reintenta un poco más tarde. En momentos al azar, como
en producción, el libro mayor se vuelve lento (un bloqueo, E/S de disco, una conmutación:
el reintento llega mientras el primer intento sigue cobrando), las respuestas se pierden por
el camino (un reinicio del balanceador, un despliegue que corta conexiones: la tarjeta se
cobró y el cliente no se enteró), o los clientes envían el mismo pago dos veces a la vez (un
bug del SDK, un doble clic). La ejecución nunca se reinicia. El primer incidente siempre es
un libro mayor lento entre 0:20 y 0:30.

```
uv run python -m live idempotency --lang es            # míralo; edita es/main.py y guarda
uv run python -m live idempotency --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/idempotency            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Sin idempotencia (dada) | cada intento cobra | cada pago reintentado se cobra dos veces (rojo); repetidas 0% |
| 1 Repite respuestas | `get` de la clave; si hay recibo devuélvelo, si no cobra y haz `set` | los reintentos tras una respuesta perdida se repiten (100%), pero un reintento que llega mientras el primero sigue cobrando, o dos intentos a la vez, siguen cobrando dos veces |
| 2 Claves reservadas | reclama la clave con `store.add(key, IN_PROGRESS, ttl)` antes de cobrar; los duplicados esperan el recibo (o lanzan `Conflict`); todo caduca | ningún cobro doble, cada intento recibe el mismo recibo; todos los objetivos OK |

Objetivos, evaluados en cada incidente: base correcta (antes), repetidos ≥ 95% de los
reintentos que llegan después del primer cobro (durante y 5 s después; "ninguno" cuando no
llegó ningún reintento tan tarde, y pasa), cobros dobles = 0 (durante), el mismo recibo para
cada intento de un pago (durante), p99 < 500 ms para los pagos empezados en los 5 s
siguientes.

- **Por qué `get` y luego `set` no basta.** Son dos pasos, a ~1 ms, con un cobro de 20 ms a
  2 s en medio. Un segundo intento que llega en ese hueco no encuentra nada y vuelve a cobrar.
  `add` (`SET NX` de Redis, o `INSERT ... ON CONFLICT DO NOTHING`) comprueba y escribe en un
  solo paso.
- **Por qué el objetivo de p99.** Un único bloqueo global alrededor de `charge` tampoco cobra
  nunca dos veces, pero entonces un cobro lento retiene a todos los demás pagos: después de un
  libro mayor lento la cola tarda mucho en vaciarse. Bloquea por clave, no por servicio.

# Laboratorio: tormenta de reintentos

*[Read in English](../README.md)*

Los usuarios envían ~100 peticiones/s (que varían despacio) a un servicio a través de tu
`Client`. En momentos al azar, como en producción, el servicio sufre una caída total (cada
llamada falla al instante: un despliegue malo, un nodo caído, un certificado caducado…) o
parcial (falla entre el 40 y el 85% de las llamadas: una réplica muerta, un nodo sin
memoria…). Los intervalos y las duraciones varían, y la ejecución nunca se reinicia. El
primer incidente siempre es una caída total entre 0:20 y 0:30.

```
uv run python -m live retry_storm --lang es            # míralo; edita es/main.py y guarda
uv run python -m live retry_storm --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/retry_storm            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Sin reintentos (dada) | una llamada, sin reintentos | los usuarios fallan (rojo) mientras está caído |
| 1 Reintentos | reintenta `ServiceError` hasta 3 veces | los reintentos vuelven al instante: backoff 1.0x, y ~4x de carga |
| 2 Reintentos + backoff | espera `backoff_delay(attempt)`: `min(cap, base * 2**attempt)` | las esperas se duplican en cada ronda (2.0x), pero todos esperan lo mismo: jitter 0% |
| 3 Reintentos + backoff + jitter | que `backoff_delay` sea al azar entre 0 y el backoff | los reintentos se reparten (jitter ~58%), pero la carga sigue ~4x |
| 4 Reintentos + backoff + jitter + presupuesto | gasta un token de `RetryBudget` (10%) en cada reintento | la carga se queda en ~1.1x; todos los objetivos OK |

Objetivos, evaluados en cada caída (total o parcial): base correcta (antes), reintentos ≥ 3%
de las llamadas (durante), backoff ≥ 1.5x (durante), jitter ≥ 25% (durante), carga < 1.5x
los 15 s anteriores (durante), servidas ≥ 90% de las peticiones empezadas en los 5 s
siguientes.

- **Backoff** es cuánto crece la espera media de una ronda de reintentos a la siguiente.
  Reintentar al instante o cada 50 ms da ~1x; el backoff exponencial da ~2x. Cuando un
  presupuesto frena casi todas las peticiones antes del segundo reintento no hay nada que
  comparar: muestra "pocos" y pasa.
- **Jitter** es cuánto varía entre usuarios la espera antes de la *misma* ronda de
  reintentos (desviación típica / media). Las esperas fijas y el backoff exponencial simple
  dan 0%: todos vuelven en el mismo momento. El jitter completo da ~58%.

**Dibujos:** `lanes` (carriles, el de siempre) y `cluster`: clientes → tu `Client` → el servicio, con las llamadas fallidas muriendo en rojo entre ellos. Pulsa `v` para cambiar, o empieza con `--view cluster`.

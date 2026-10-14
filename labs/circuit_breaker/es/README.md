# Laboratorio: circuit breaker

*[Read in English](../README.md)*

Nuestro servicio recibe ~100 peticiones/s con un pool de 24 workers. Cada petición retiene
un worker mientras llama a UNA dependencia a través de tu `Client`: "payments" (pagos, el
60%) o "recs" (recomendaciones, el 40%). En momentos al azar, como en producción, una
dependencia se vuelve muy lenta: de 4 a 10 s por llamada (una tormenta de GC, un bloqueo,
una degradación de red, un proveedor que nos limita). Los usuarios se rinden a los 2 s,
pero el servidor no lo sabe: su worker sigue esperando. El primer incidente siempre es
"recs", 8 s por llamada, entre 0:20 y 0:30.

```
uv run python -m live circuit_breaker --lang es            # míralo; edita es/main.py y guarda
uv run python -m live circuit_breaker --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/circuit_breaker            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Sin protección (dada) | las llamadas esperan lo que haga falta | workers 24/24, y la dependencia sana también falla (~5% servidas) |
| 1 Timeouts | `asyncio.timeout(TIMEOUT)` alrededor de la llamada | las llamadas se cortan a 1 s, pero el pool se sigue llenando: sana ~15–70% |
| 2 Timeouts + bulkhead | un `Bulkhead(10)` por dependencia | la dependencia sana va bien; quien usa la lenta aún espera 1 s para fallar |
| 3 Timeouts + bulkhead + breaker | un `CircuitBreaker` por dependencia | la puerta se cierra: las llamadas fallan en menos de 1 ms, y se vuelve a abrir después |

Objetivos, evaluados en cada lentitud: base correcta (antes); llamadas a la dependencia
lenta ≤ 1.2 s (p99, durante); peticiones a la dependencia sana servidas ≥ 99% (durante);
las peticiones a la lenta fallan rápido, p99 < 50 ms una vez que lleva 3 s lenta
(durante); las peticiones a ella vuelven a servirse ≥ 95% desde 7 s después de que se
recupere (después).

La gráfica muestra los workers ocupados cada segundo (blanco: llamadas a una dependencia
sana; naranja: llamadas a la lenta), frente al tamaño del pool.

**Segundo dibujo.** Pulsa `v` (o `--view cluster`) para ver la topología: clientes → servicio → pagos y recomendaciones. Las llamadas lentas se quedan junto a su dependencia ocupando un worker; las rechazadas y las fallidas mueren en rojo en su arista.

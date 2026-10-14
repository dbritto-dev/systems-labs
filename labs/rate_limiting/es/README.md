# Laboratorio: limitación de tráfico

*[Read in English](../README.md)*

20 clientes llaman a una API a través de tu `RateLimiter`. El backend atiende 15 peticiones a
la vez, 100 ms cada una (150 peticiones/s); a partir de ahí las peticiones esperan en una cola
corta, y una cola llena las rechaza (503). Normalmente los clientes envían ~100 peticiones/s
entre todos.

En momentos al azar, como en producción, unos pocos clientes inundan la API a ráfagas: un
proceso por lotes que envía su trabajo a trozos, un scraper que sincroniza sus ráfagas con el
reinicio de la ventana, una versión del SDK con un bug en los reintentos. La primera avalancha
siempre son 5 clientes entre 0:20 y 0:35. La ejecución nunca se reinicia.

```
uv run python -m live rate_limiting --lang es            # míralo; edita es/main.py y guarda
uv run python -m live rate_limiting --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/rate_limiting            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` (`RateLimiter.allow`) | Lo que ves |
|---|---|---|
| 0 Sin límite (dada) | deja pasar todo | el backend se satura; también fallan los clientes que no hicieron nada mal |
| 1 Ventana fija | como mucho `rate` (20) por cliente en cada ventana de 1 s | la avalancha se rechaza, pero una ráfaga que cruza un reinicio deja pasar el doble |
| 2 Token bucket | por cliente: rellena 20 tokens/s, hasta 10 | suave (pico 1.4x), pero 5 clientes con tope juntos aún saturan el backend |
| 3 Bucket + reparto justo | rellena a min(rate, capacity / clientes activos) | la avalancha recibe su parte justa; el resto es servido |

Objetivos, evaluados en cada avalancha: base correcta (antes); peticiones de los clientes en
avalancha limitadas ≥ 50% (durante); pico ≤ 1.6x (lo máximo que un cliente en avalancha pasa
en 1 s, frente a su ritmo) (durante); el resto de clientes servido ≥ 99% (durante); servidas
≥ 99% en los 5 s siguientes, para los clientes que no inundaron.

**Dibujos:** `lanes` (carriles, el de siempre) y `cluster`: clientes → el limitador → el backend; las peticiones limitadas mueren en rojo antes del limitador, los 503 después. Pulsa `v` para cambiar, o empieza con `--view cluster`.

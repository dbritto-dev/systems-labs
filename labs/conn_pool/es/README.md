# Laboratorio: pool de conexiones

*[Read in English](../README.md)*

Los usuarios envían ~100 peticiones/s (que varían despacio). Cada petición le pide a tu
`Pool` una conexión a la base de datos, ejecuta una consulta y devuelve la conexión. Abrir
una conexión cuesta ~40 ms (TLS, autenticación, un proceso nuevo en el servidor); una
consulta ~8 ms. La base de datos admite como mucho **50** conexiones abiertas ("too many
connections" a partir de ahí) y va más lenta en cuanto más de ~20 trabajan a la vez.

En momentos al azar, como en producción, la base de datos **va lenta** (autovacuum, un
informe largo que bloquea tablas, una copia de seguridad que satura los discos, un índice
borrado) o el **tráfico se dispara** de 5 a 7 veces (un correo de marketing, un cron que
lanza trabajo para cada usuario). El primer incidente siempre es una lentitud entre 0:20 y
0:32. La ejecución nunca se reinicia: el pool y sus conexiones siguen de un minuto al otro.

```
uv run python -m live conn_pool --lang es            # míralo; edita es/main.py y guarda
uv run python -m live conn_pool --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/conn_pool            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Conexión nueva (dada) | abre y cierra una conexión por petición | reuso 0%; una lentitud o un pico llega a 50 conexiones y se rechazan peticiones |
| 1 Pool | guarda las conexiones liberadas y vuelve a darlas | reuso ~100%; una lentitud aún lleva el pool a 50: peticiones rechazadas |
| 2 Pool acotado | nunca abras más de `max_size` (20); espera a que se libere una | sin rechazos, pero durante una lentitud las peticiones esperan de 2 a 7 s |
| 3 Pool acotado + timeout | ríndete tras `timeout` (0.5 s): lanza `PoolTimeout` | las esperas se quedan en 0.5 s; algunas peticiones fallan rápido mientras va lenta |

Objetivos, evaluados en cada incidente: base correcta (antes), reuso ≥ 90% de las
peticiones servidas (antes), ningún error de "too many connections" (durante), espera p99
por una conexión < 1 s (durante), ≥ 95% de las peticiones empezadas en los 5 s siguientes
servidas en menos de 1 s (después).

Una petición que sigue esperando cuando se evalúa un incidente cuenta con el tiempo que lleva
esperado. Un pool más grande no hace más rápida una base de datos lenta: pasadas ~20
conexiones trabajando a la vez, cada consulta tarda más.

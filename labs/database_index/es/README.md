# Laboratorio: índices de base de datos

*[Read in English](../README.md)*

Una tabla `users` empieza con 20,000 filas y no deja de crecer: ~5 altas/s, y de vez en
cuando una carga masiva. Los usuarios hacen login (`find_by_email`, ~30/s) y los paneles
preguntan quién se dio de alta en un país en un rango de tiempo (`signups_between`, ~2/s).
La base de datos tiene 4 workers; cada consulta cuesta 0.2 ms más 5 µs por fila que lee, y
un usuario se rinde tras esperar 2 s a un worker. Cada respuesta se comprueba: una errónea
es una consulta fallida.

Los incidentes llegan al azar, como en producción: una carga masiva (10,000–20,000 filas con
fechas de alta antiguas, en unos segundos), un informe nuevo que lanza muchas consultas por
rango grandes, o un pico de logins. La ejecución nunca se reinicia, así que la
tabla solo crece. El primer incidente siempre es una carga a las 0:20.

```
uv run python -m live database_index --lang es            # míralo; edita es/main.py y guarda
uv run python -m live database_index --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/database_index            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Lectura completa (dada) | cada consulta recorre la tabla | un login lee ~20,000 filas y tarda ~0.1 s; la primera carga lleva el p99 por encima de 1 s y las siguientes hacen que los usuarios se rindan |
| 1 Índice hash | un dict email -> posición para `find_by_email` | un login lee 1 fila, pero un rango sigue leyendo ~900x las filas que devuelve (p99 ~200 ms) |
| 2 Índice hash + compuesto | por país, una lista ordenada de (tiempo, posición); bisect en `signups_between` | cada consulta lee solo lo que devuelve (1.0x); p99 por debajo de 1 ms; todos los objetivos OK |

Objetivos, evaluados en cada incidente: filas leídas por login ≤ 5 (los 15 s de antes), filas
leídas por fila que devuelve un rango ≤ 2x (los 15 s de antes), latencia p99 < 100 ms y ≥ 99%
respondidas (consultas empezadas durante el incidente; un usuario que se rindió cuenta como
fallo).

- La etapa se evalúa por las **filas leídas**, no por la latencia: una lectura completa es
  rápida con una tabla pequeña, y se vuelve más lenta cada día a medida que la tabla crece.
- Las cargas insertan filas con **tiempos antiguos**, así que el índice compuesto tiene que
  seguir ordenado: usa `insort`, no `append`.
- La gráfica es el tiempo ocupado de la base de datos como % de los 4 workers, coloreado por
  las filas que leyó cada consulta: blanco unas pocas, naranja cientos o miles, naranja oscuro
  una lectura completa.

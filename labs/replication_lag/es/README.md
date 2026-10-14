# Laboratorio: retraso de réplicas

*[Read in English](../README.md)*

Una base de datos primaria y 4 réplicas de lectura asíncronas (r1..r4). ~200 usuarios
(sesiones) hacen ~200 operaciones/s: el 15% son escrituras (su propio perfil, o una de 20
páginas populares) y el resto, lecturas. Cada escritura se confirma en el primario y llega a
cada réplica 50–200 ms después. Tu `Router` decide adónde va cada lectura, sabiendo la
posición en el log (LSN) de cada réplica según su último informe, cada 100 ms.

En momentos al azar, como en producción, una réplica se retrasa 2–10 s (una consulta
analítica larga, autovacuum, una degradación de red), una réplica se reinicia y reproduce lo
que se perdió, o un pico de escrituras retrasa a todas las réplicas. La ejecución nunca se
reinicia. El primer incidente siempre es r2 retrasándose 6 s entre 0:20 y 0:30.

```
uv run python -m live replication_lag --lang es            # míralo; edita es/main.py y guarda
uv run python -m live replication_lag --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/replication_lag            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Cualquier réplica (dada) | lee de cualquier réplica que esté arriba | durante un retraso, ~120–230 usuarios no ven su propia escritura y ~50–220 páginas retroceden |
| 1 Lee tus escrituras | guarda en `wrote` el LSN de la última escritura de cada sesión; en `pick`, solo réplicas con `lsn >=` ese | nadie pierde lo suyo, pero ~40–80 páginas aún retroceden mientras una réplica se retrasa |
| 2 Lecturas monótonas | guarda también la versión más nueva que cada sesión vio de cada clave (`saw`) | nada sale mal; el primario recibe ~6–8% de las lecturas (~12–21% en un pico de escrituras) |

Leer todo del primario también da 0 lecturas malas, pero pone el 100% de las lecturas en el
primario: no cumple el tercer objetivo y se queda en la etapa 0.

Objetivos, evaluados por incidente desde su inicio hasta 5 s después de que termine:

- **Propias = 0**: ninguna lectura del perfil de un usuario devuelve una versión más vieja
  que la última escritura que ese usuario había hecho al empezar la lectura.
- **Retrocesos = 0**: ninguna lectura devuelve una versión de una clave más vieja que la que
  la sesión ya había visto.
- **Primario ≤ 35%**: como mucho el 35% de las lecturas respondidas van al primario.

La ventana en vivo muestra el primario (arriba a la izquierda) y las réplicas, coloreadas
según cuánto se retrasan; los puntos azules son escrituras camino de cada réplica (una
réplica retrasada lleva una larga estela), los blancos son lecturas y las manchas rojas,
lecturas malas.

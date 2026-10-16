# Laboratorio: migración sin caída

*[Read in English](../README.md)*

La app guarda el nombre de cada usuario en `users.fullname` (10.000 filas), y la próxima
versión lo renombra a `users.display_name`. Seis instancias de la app atienden ~100
peticiones/s (el 70% lee un nombre, el 30% lo cambia). Una versión se despliega una instancia
cada 2 s, así que durante un rato las instancias **viejas** (leen y escriben la columna vieja)
y las **nuevas** (ejecutan tus `read_name` y `write_name`) comparten la base de datos. Tu
`migrate` empieza al abrirse la ventana, 2 s antes que el despliegue, y debe haber borrado la
columna vieja antes de 60 s.

La carga de la base de datos es el tráfico de la app (~0.3) más lo que se ejecute además: tus
copias, las instancias recién reiniciadas (con cachés en frío), un pico de tráfico, y las
lecturas que caen en el primario cuando la réplica va más de 2 s atrasada y sale del grupo.
Cada sentencia se vuelve más lenta cuanto más sube la carga; una copia además bloquea las
filas que copia hasta que se consolida, y la réplica tiene que aplicar cada fila que cambia.

Los incidentes son **ventanas de migración**, al azar como las versiones en producción; cada
una renombra otra columna (email → email_address, phone → phone_number, ...). Algunas traen
problemas: el despliegue se **revierte a medias** (una alarma del canario, un pico de errores
en otro servicio) y luego vuelve a avanzar, la **réplica se atrasa** (una consulta analítica
larga, un disco saturado), o la **base de datos se carga** (un pico de tráfico, la tarea
nocturna de facturación). La primera ventana siempre es a las 0:20, con una vuelta atrás. La
ejecución nunca vuelve a empezar: la tabla, las instancias y el reloj siguen.

```
uv run python -m live zero_downtime_migration --lang es            # míralo; edita es/main.py y guarda
uv run python -m live zero_downtime_migration --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/zero_downtime_migration            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves (primera ventana, 12 semillas) |
|---|---|---|
| 0 Renombrar de golpe (dada) | `migrate` renombra la columna de golpe; el código nuevo solo usa el nombre nuevo | cada instancia vieja falla hasta que la reemplazan, y otra vez tras la vuelta atrás: de 1.003 a 1.352 errores |
| 1 Expandir/contraer | añade la columna, escribe ambas (`m.write_old`), lee la vieja (`m.read_new`), un `db.copy` de todas las filas, cambia y borra tras `fleet.released()` | sin errores, pero la copia bloquea todas las filas 7.5 s (p99 de escritura de 6.5 a 7.1 s), y quedan de 102 a 177 nombres erróneos escritos por instancias viejas durante la vuelta atrás |
| 2 Relleno frenado y verificado | `backfill`: BATCH filas por copia, PAUSE entre ellas, espera mientras `busy()`; `verify` vuelve a copiar los lotes que difieren | sin errores, p99 de escritura de 25 a 29 ms, ningún nombre erróneo, hecha en 42 a 49 s |

Sin `verify` los lotes aún dejan de 21 a 54 nombres erróneos tras la vuelta atrás; sin `busy()`
las copias siguen mientras las instancias reiniciadas se calientan, y el p99 de escritura llega
a 64–102 ms (y a mucho más cuando la réplica se atrasa o la base de datos se carga).

Objetivos, evaluados por ventana: errores = 0 (peticiones que fallaron, durante); p99 de
escritura < 40 ms (escrituras empezadas durante la ventana); nombres erróneos = 0 (lecturas
que devolvieron un nombre distinto del último, más las filas que quedan con un nombre erróneo
en la columna que lee la app al final; después); hecha en ≤ 60 s (la columna vieja borrada, la
nueva ahí; después).

**Dibujo de carriles** (el de inicio). Los usuarios esperan su nombre (en naranja cuando una
escritura tarda más de 40 ms). La puerta son las instancias de la app: naranja mientras
conviven viejas y nuevas, cerrada en rojo mientras las peticiones fallan con una columna que
ya no existe. Las respuestas se apagan en la puerta: verde, rojo (fallida), naranja oscuro (un
nombre erróneo). El servidor es la base de datos: su indicador es la carga (naranja por encima
del 60%, rojo por encima del 72%), su contorno morado mientras el relleno copia. Debajo: qué
columnas guardan el nombre y cuánto se ha copiado. La gráfica es la carga, segundo a segundo:
la app (blanco), otro trabajo (naranja) y tus copias (morado), con la línea donde el p99 de
escritura pasa de 40 ms; las copias y los problemas aparecen sombreados.

**Dibujo del clúster.** Pulsa `v` (o `--view cluster`): las seis instancias arriba (blanco la
versión vieja, azul la nueva, apagadas mientras se reinician, rojas mientras fallan), y debajo
quien ejecuta la migración, el primario y su réplica. Las peticiones vuelan a una instancia y
de ahí al primario, coloreadas por las columnas que tocan (blanco la vieja, azul la nueva,
naranja claro ambas: una doble escritura); las que fallan mueren en rojo. Los puntos morados
salen de quien migra mientras copia; los naranjas van a la réplica mientras se atrasa.

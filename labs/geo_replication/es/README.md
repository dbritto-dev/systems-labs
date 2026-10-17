# Laboratorio: replicación geográfica

*[Read in English](../README.md)*

Un servicio de perfiles y ajustes corre en tres regiones, Estados Unidos (`us`), Europa (`eu`) y
Asia-Pacífico (`ap`), un `RegionNode` en cada una, sobre una red simulada con distancias reales: ~1 ms
dentro de una región, ~70 ms de ida entre us y eu, ~100 ms entre us y ap, ~150 ms entre eu y ap
(±20%). 600 usuarios, 200 en cada región, leen y escriben su propio perfil y leen el de otros:
~200 operaciones por segundo, 20% escrituras; tras guardar, la mitad mira su perfil enseguida. El
balanceador global manda a cada usuario a su propia región; cuando una región cae, mueve a sus
usuarios a la siguiente (us → eu, eu → us, ap → us) en ~1 s, y los devuelve 0.5 s después de que se
recupera (las cachés de DNS hacen ambos cambios graduales, en 4 s). La aplicación del usuario
reintenta una vez, en la siguiente región, ante un timeout (0.6 s) o un error, y evita 3 s la región
que le falló. Una región atiende 320 lecturas y escrituras por segundo.

En momentos al azar, como en producción: cae una región entera (un corte de luz, un cambio de
configuración erróneo, una caída de la nube, una falla de refrigeración), una región queda aislada
de las otras dos aunque sus usuarios todavía llegan a ella (un corte de fibra, una fuga BGP, una
regla de cortafuegos), el enlace entre dos regiones se vuelve 150–350 ms más lento y pierde el 10% de
sus mensajes (un cable submarino cortado), o una región tiene su pico (2.5–3 veces su tráfico). La
ejecución nunca se reinicia. El primer incidente siempre aísla a us, la primaria de las etapas 0 y 1, de eu y ap de 0:20 a
0:32 (un corte de fibra); sus propios usuarios todavía llegan a ella.

```
uv run python -m live geo_replication --lang es          # míralo; edita es/main.py y guarda
uv run python -m live geo_replication --lang es --lesson # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/geo_replication          # x = aún no, X = hecho
```

Tres dibujos (`v` cambia): **pares** (abre con este) muestra las tres regiones en un triángulo, us
arriba, cada enlace con su latencia de ida; los usuarios entran por el balanceador global a la
izquierda (rojo mientras una región está caída), y la petición de un usuario vuela a la región que
la atiende: blanca en casa, naranja en otra. En los enlaces, cada sentido por su carril (por la
derecha): naranja una petición reenviada al otro lado de un océano y su respuesta, azul la replicación
(también sus confirmaciones y las búsquedas). El indicador de una región es su carga frente a las 320/s
que puede atender; su borde y la palabra debajo dicen cuántas escrituras confirmadas le faltan
(`eu −120`), o que está caída o aislada. **clúster** muestra las regiones una al lado de otra, us,
eu y ap (con su nombre bajo cada columna), como columnas de tres nodos (sus zonas), coloreadas según cuántas escrituras
confirmadas le faltan a la región: azul al día, naranja atrasada, rojo caída; una región aislada
queda cercada por una línea roja discontinua. Las peticiones de los usuarios entran desde la
izquierda: blancas a su propia región, naranjas a otra. Entre regiones, a su velocidad real: naranja
la petición de un usuario reenviada al otro lado de un océano y su respuesta, azul la replicación; un mensaje que
la red perdió muere a mitad de camino en rojo. **carriles** muestra cada operación a la izquierda, el
balanceador global como la puerta (roja mientras una región está caída) y las regiones como el
servidor, con su indicador en la carga de la región más ocupada; las respuestas son verdes
(rápidas), naranjas (lentas: cruzaron un océano o esperaron un reintento), moradas (una lectura sin
la escritura del propio usuario) o rojas (fallidas).

| Etapa | En `es/main.py` | Qué ves |
|---|---|---|
| 0 Una región primaria (dada) | cada región reenvía cada lectura y escritura a us | puntos naranjas cruzan un océano en cada petición de eu y ap (p99 ~180–250 ms); con us aislada, sus peticiones esperan un timeout y un reintento en us (p99 ~650 ms), y cada escritura vive solo en us; cuando us cae, todo falla |
| 1 Réplicas de lectura | cada región responde las lecturas con su copia; us confirma las escrituras y las envía (`ship`) en lotes cada 0.1 s (`on_replicate` las guarda) | las lecturas se quedan en casa (p99 ~10–15 ms); pero quien guarda y recarga no ve su cambio (morado), las escrituras recientes existen solo en us (todas mientras está aislada), las de eu y ap esperan un reintento al otro lado del océano, y con us caída nadie puede escribir |
| 2 Escrituras en cada región | cualquier región acepta una escritura y la confirma cuando la primera de las otras dos la tiene (`replicate`, `send_to`); las escrituras perdidas se vuelven pistas (`hand_off`); una lectura más vieja que el token de sesión busca (`fetch`) la nueva | con us aislada, sus escrituras se rechazan allí y las acepta eu, y sus lecturas en casa esperan al token en vez de mostrar datos viejos; con us caída, eu recibe a sus usuarios; todos los objetivos OK |

Objetivos, evaluados por incidente, sobre lo que pasa desde su inicio hasta 5 s después de su fin:

- **Lectura p99 ≤ 50 ms** y **escritura p99 ≤ 400 ms**, en la peor región, para los usuarios
  atendidos en su propia región (los usuarios de una región caída o aislada se atienden al otro
  lado de un océano hagas lo que hagas: cuentan para los demás objetivos). Una escritura puede
  cruzar un océano (eu → ap y vuelta: ~300 ms), nunca dos.
- **Lecturas viejas = 0**: una lectura del propio perfil a la que le falta una escritura que el
  usuario vio confirmada.
- **Éxito ≥ 99%** de todas las operaciones, tras el único reintento de la aplicación.
- **Escrituras en riesgo = 0**: cada 0.2 s el comprobador mira dentro del `store` de cada región y
  cuenta las escrituras confirmadas que tiene una sola región. Son las que se llevaría una región
  perdida para siempre: la replicación asíncrona siempre tiene algunas (RPO > 0). Contamos esas, no
  "escrituras perdidas", porque aquí una región vuelve con su disco; en un desastre real, quizá no.

Por qué estas decisiones:

- **Por qué una escritura por usuario y gana el último.** Un perfil solo lo escribe su dueño, una
  petición a la vez, así que dos regiones nunca aceptan escrituras de la misma clave a la vez salvo
  alrededor de un failover, y entonces la versión más nueva es la escritura posterior. Por eso
  bastan versiones simples (aquí la hora de la escritura; en un sistema real, un reloj lógico
  híbrido). Los datos que escriben muchos a la vez (un documento compartido, un contador) necesitan
  resolver conflictos por clave o CRDT (mira `vector_clocks_crdts`).
- **Por qué confirmar tras una segunda región, no todas.** Esperar a todas hace que una región caída
  detenga todas las escrituras. Esperar a la primera de las otras dos cuesta un océano y sobrevive a
  cualquier región: el "sobrevivir a una región" de CockroachDB, las configuraciones multirregión de
  Spanner.
- **Por qué guardar primero en local, y negarse cuando está sola.** Una región aislada todavía tiene
  usuarios. Si confirmara sus escrituras, vivirían solo ahí (en riesgo), y las otras regiones
  aceptarían escrituras en conflicto. Las guarda, responde un error, y la aplicación escribe de nuevo
  en una región que llega a otra.
- **Por qué tokens de sesión.** La aplicación mueve a un usuario entre regiones (failover,
  reintentos, evitar la región que le falló), y una región que estuvo caída o aislada vuelve
  atrasada. El token es la versión más nueva que el usuario escribió o vio; una región con una copia
  más vieja busca la nueva o se niega, nunca responde con el pasado.
- **Por qué pistas.** Una región que se perdió escrituras seguiría atrasada hasta que cada clave se
  escriba de nuevo; las otras guardan lo que se perdió y se lo reenvían cada segundo hasta que lo
  confirme.

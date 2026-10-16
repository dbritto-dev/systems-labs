# Laboratorio: partición caliente

*[Read in English](../README.md)*

Un almacén clave/valor está repartido en seis particiones (p0 ... p5) según un hash de la clave,
como DynamoDB, Cassandra o un Redis repartido; cada partición atiende 150 peticiones por segundo
y rechaza peticiones cuando su cola guarda más de 0,2 s de trabajo. Los usuarios dan me gusta,
hacen clic y miran cosas: ~120 operaciones por segundo sobre contadores (60% lecturas de una
cuenta, 40% incrementos) sobre 5.000 claves con una popularidad tipo Zipf, todas a través de tu
`Counters` (`incr(key)`, `read(key)`). Cada partición está ocupada un ~15% del tiempo.

En momentos al azar, como en producción, una clave explota: la publicación de una famosa se hace
viral (me gusta), todo el mundo hace clic en el enlace de un boletín (clics), una oferta relámpago
vende un producto (ventas, y su página lee la cuenta) o un bot machaca un id (lecturas). Entre 200
y 400 operaciones por segundo sobre una clave: más de lo que atiende su partición, mientras las
otras cinco están ociosas. Su tráfico sube en 1,5 s, se mantiene de 5 a 22 s y baja a una cola de
tráfico que dura un minuto. La ejecución nunca se reinicia. El primer incidente siempre es una
publicación viral entre 0:20 y 0:32.

```
uv run python -m live hot_partition --lang es            # míralo; edita es/main.py y guarda
uv run python -m live hot_partition --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/hot_partition            # x = aún no, X = hecho
```

Dos dibujos (`v` cambia): **clúster** (abre con este) muestra las seis particiones como nodos,
con un color según su ocupación (azul bajo el 50%, naranjas, rojo sobre el 90%), y cada petición
al almacén volando a su partición: blanca una normal, morada una sobre la clave caliente, naranja
una petición de más de una lectura que suma subclaves, azul las que vuelven a juntar subclaves;
una rechazada muere a medio camino, en rojo. **carriles** muestra las operaciones de los usuarios
a la izquierda, tu `Counters` como la puerta y el almacén como el servidor, con su indicador la
ocupación de la partición más cargada; las respuestas son verdes (una petición), naranjas (sumó
subclaves), azules (de la caché) o rojas (rechazada).

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Hash por clave (dada) | cada operación va a la propia clave | un nodo se pone rojo, le llueven puntos morados que mueren en rojo; los demás siguen azules |
| 1 Claves repartidas | `heat` cuenta las escrituras de cada clave en los últimos 0,25 s; con `HOT` escrituras/s, `salt` la reparte: las escrituras van a una de seis subclaves al azar (`pick`), y `keys_of` nombra las seis, así `read` las suma | las escrituras de la publicación viral se reparten por las seis particiones; pero cada lectura cuesta ahora seis peticiones (naranja), y sigue repartida cuando se enfría; un bot (solo lecturas) sigue saturando su partición |
| 2 Reparto adaptativo | `salts_for`: N según el calor; guarda en caché 0,5 s la cuenta de una clave caliente de lecturas o repartida; `cool`: tras 2 s bajo `COOL` escrituras/s, escribe en la propia clave, y `fold` junta las subclaves 1 s después | la clave se reparte solo mientras está caliente, las lecturas del bot salen de la caché, y al enfriarse el naranja se acaba; todos los objetivos OK |

Objetivos, evaluados en cada incidente: la partición más cargada bajo el 90% (su ocupación media
mientras la clave está caliente, desde el segundo 1), rechazadas ≤ 1% y p99 ≤ 100 ms (las
operaciones desde el inicio hasta 5 s después del final), incrementos perdidos = 0 (cada medio
segundo, lo que guarda el almacén en las claves que nombra `keys_of` debe sumar justo los
incrementos confirmados al cliente; una cuenta que se está moviendo al juntar subclaves solo falta
un instante) y peticiones por operación ≤ 1.1x cuando se enfría (de 8 a 18 s después del final,
mientras la clave aún recibe visitas).

- **Por qué repartir perjudica a las lecturas.** La cuenta de una clave repartida está en N
  subclaves, así que una lectura tiene que pedir las N: repartir la clave que lee un bot multiplica
  su carga por seis en vez de repartirla. Las lecturas calientes piden una caché: una cuenta de me
  gusta de medio segundo de antigüedad sirve.
- **Por qué volver a juntar.** Una clave sigue siendo algo popular mucho después de dejar de ser
  viral. Si se queda repartida para siempre, cada una de sus lecturas cuesta seis peticiones; con
  muchas publicaciones virales pasadas, las sumas se acumulan.
- **Por qué esperar antes de juntar.** Una escritura mandada a `key#3` justo antes de dejar de
  repartir puede estar aún en camino. Si tomas la cuenta de `key#3` demasiado pronto, esa escritura
  llega después: perdida. Deja de escribir en las subclaves, espera a las escrituras en vuelo y
  luego mueve las cuentas.
- **Por qué el ancho solo crece.** Si N pasa de 3 a 6 y luego vuelve a 4, las subclaves 4 y 5 aún
  guardan cuentas: una lectura de solo cuatro subclaves las pierde.

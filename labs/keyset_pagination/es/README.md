# Laboratorio: paginación por clave

*[Read in English](../README.md)*

Una API lista un feed de ~40,000 publicaciones, de la más nueva a la más vieja, 20 por página, a
través de tres servidores de API, cada uno con su `FeedAPI.list_posts(cursor)` sobre una misma base
de datos (4 workers, 10 µs por fila leída). ~10 personas por segundo abren el feed y bajan 1–8
páginas; un indexador de búsqueda recorre el feed entero, página tras página, y vuelve a empezar al
llegar al final. Mientras tanto se escriben ~4 publicaciones por segundo arriba y se borran ~0.5 por
segundo. Cada página se compara con la verdad: una publicación que existía cuando el cliente empezó
a recorrer, y sigue existiendo, tiene que salir exactamente una vez. En momentos al azar, como en
producción, una carga masiva escribe cientos de publicaciones con un solo `created_at` (una
transacción, un solo `now()`; un CSV; una migración), un momento viral mete 40–120 publicaciones por
segundo arriba, una purga de spam borra 100–300 publicaciones recientes por segundo, o procesos de
sincronización (una reindexación, una exportación de un socio) recorren el feed entero a toda
velocidad. La ejecución nunca se reinicia. El primer incidente es siempre una carga masiva en
0:20–0:30.

```
uv run python -m live keyset_pagination --lang es          # míralo; edita es/main.py y guarda
uv run python -m live keyset_pagination --lang es --lesson # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/keyset_pagination          # x = todavía no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 OFFSET (dada) | `select(20, offset=n)`, el cursor es el offset | ~1,000 publicaciones repetidas en la primera carga (morado: lo que se escribe por encima de los lectores baja cada fila un puesto), miles saltadas en una purga (rojo), ~1,500–1,900 filas leídas por página y un p99 del fondo de 70–280 ms (las páginas del indexador leen todo lo que tienen encima) |
| 1 Clave sobre `created_at` | `select(20, older_than=ultima.created_at)`, el cursor es ese número | 20 filas por página, p99 del fondo ~3 ms, nada repetido; pero cada recorrido que llega al único `created_at` de la carga salta las publicaciones que no cupieron en su página: ~5,000–8,600 saltadas (rojo), y otra vez cada vez que el indexador pasa por una carga vieja |
| 2 Clave sobre `(created_at, id)` | `older_than=(created_at, id)` de un `encode_cursor` opaco; `decode_cursor` lanza `BadCursor` | nada saltado ni repetido, 20 filas por página, p99 del fondo ~3 ms; todos los objetivos OK |

Objetivos, evaluados por incidente: base correcta (páginas respondidas antes), saltadas = 0,
repetidas = 0, p99 del fondo < 25 ms (la página 10 de un recorrido o más) y filas leídas por página
≤ 40 (todo para las páginas pedidas durante el incidente).

Dos dibujos: `lanes` (se abre primero) muestra cada petición de página volando hacia la API,
coloreada por las filas que la base de datos leyó para ella (blanco una página, naranja más oscuro
para los miles de OFFSET), y lo que volvió en la puerta: verde una página correcta, rojo una que
saltó publicaciones, morado una que las repitió; el indicador es la parte ocupada de la base de
datos. `cluster` muestra los tres servidores de API y los 4 workers de la base de datos: cada
worker se colorea por la consulta que ejecuta (un OFFSET profundo lo deja naranja oscuro), y las
páginas equivocadas vuelven en rojo o morado; pulsa `v` para cambiar.

- **Por qué OFFSET repite y salta.** OFFSET 40 significa "sáltate las 40 primeras filas *tal como
  están ahora*". Una publicación escrita arriba entre dos páginas baja todo un puesto, y la página
  siguiente empieza con la última que viste; una borrada por encima sube todo, y otra no se
  muestra nunca.
- **Por qué OFFSET es lento en el fondo.** El índice no puede saltar a la fila 20,000: la base de
  datos lo recorre desde arriba y tira las filas. Las páginas del indexador van más lentas cuanto
  más baja.
- **Por qué `created_at` solo no basta.** No es único. Una carga masiva en una transacción marca
  600 publicaciones con un solo `now()`: la página acaba en medio de ellas, y `< t` salta el resto
  (`<= t` las volvería a mostrar, y un proceso podría quedarse dando vueltas en ellas).
- **Por qué un cursor guarda valores.** Un cursor que guarda el id de la última publicación y la
  vuelve a buscar se rompe cuando se borra (una purga): un 400, el cliente vuelve a empezar y
  repite publicaciones. `(created_at, id)` sigue diciendo dónde continuar aunque ya no exista.
- **Por qué opaco.** Los clientes tratan el cursor como una ficha, así que puedes cambiar lo que
  lleva dentro; un cursor que no se puede decodificar es un 400, nunca un 500 ni otra página. Para
  que los clientes no puedan falsificarlo, fírmalo (un HMAC).

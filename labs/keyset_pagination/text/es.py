"""Laboratorio keyset_pagination, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Paginación por clave"
SUMMARY = "Los clientes recorren un feed que no para de cambiar. Cada publicación una vez, rápido a cualquier fondo."
PARAMS = {"rate": "lectores por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"import": "CARGA", "viral": "VIRAL", "cleanup": "PURGA", "sync": "SINCRO", "calm": "CALMA"}
CAUSES = {
    "txn_now": "una inserción masiva en una transacción: now() es el mismo para cada fila",
    "csv_import": "un administrador importa un CSV, cada fila con la hora de la subida",
    "migration": "publicaciones migradas de la aplicación vieja, todas con la hora de la migración",
    "seed_job": "un proceso llena una comunidad nueva con publicaciones de bienvenida",
    "breaking_news": "última hora: todo el mundo publica a la vez",
    "match_final": "los últimos minutos de una final de copa",
    "trending": "una etiqueta se vuelve tendencia",
    "celebrity": "llega una celebridad y sus fans entran en masa",
    "spam_wave": "moderación quita la ola de spam de anoche",
    "bot_ban": "se bloquea una red de bots y se borran sus publicaciones",
    "erasure": "se procesan en bloque peticiones de borrado de cuentas",
    "takedown": "una retirada legal quita un lote de publicaciones",
    "reindex": "el clúster de búsqueda se reconstruye desde cero",
    "partner_export": "un socio exporta el feed entero por la API",
    "warehouse": "el almacén de datos se rellena desde la API",
    "app_release": "una versión nueva de la aplicación copia el feed para leer sin conexión",
}

STAGES = [
    StageText("OFFSET",
              "Reto: las filas se mueven y hay publicaciones repetidas o perdidas; el fondo lo lee todo.",
              "Etapa 1: un cursor por clave: WHERE created_at < el último"),
    StageText("Clave created_at",
              "Reto: rápido a cualquier fondo, pero salta publicaciones de igual created_at. Desempata.",
              "Etapa 2: un cursor opaco (created_at, id)"),
    StageText("Clave (created_at, id)",
              "Resuelto: cada publicación una sola vez, ~20 filas leídas por página a cualquier fondo.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "list_posts() debe responder"),
    "skipped": GoalText("Saltadas = 0", "desempata con el id"),
    "dup": GoalText("Repetidas = 0", "cursor por clave, no OFFSET"),
    "deep": GoalText("p99 fondo < 25ms", "busca la clave, no OFFSET"),
    "rows": GoalText("Filas/página ≤ 40", "WHERE ... < cursor"),
}

LEGEND = {"idle": "en reposo", "cheap": "página ~20 filas", "scans": "filas leídas 10x,100x,1000x",
          "skipped": "saltadas", "repeated": "repetidas", "served": "servida",
          "limit": "4 workers", "incident": "incidente"}

STRINGS = {
    # incidentes
    "title_import": "Carga",
    "title_viral": "Viral",
    "title_cleanup": "Purga",
    "title_sync": "Sincro",
    "import_start": "{n:,.0f} publicaciones escritas con un solo created_at: {cause}",
    "import_end": "la carga ha terminado",
    "viral_start": "{n:.0f} publicaciones/s arriba, el doble de lectores: {cause}",
    "viral_end": "se publica al ritmo normal",
    "cleanup_start": "se borran {n:.0f} publicaciones recientes por segundo: {cause}",
    "cleanup_end": "la limpieza ha terminado",
    "sync_start": "{n:.0f} procesos más recorren el feed entero: {cause}",
    "sync_end": "los procesos de sincronización han parado",
    "warn_skipped": "{n:,} publicaciones saltadas",
    "warn_dup": "{n:,} publicaciones mostradas dos veces",
    # valores de los objetivos
    "count": "{n:,}",
    # el panel
    "tile_skipped": "Saltadas",
    "tile_dup": "Repetidas",
    "tile_rows": "Filas/pág",
    "stat_deep": "p99 fondo",
    "bar_readers": "Lectores",
    "bar_sync": "Procesos",
    "bar_posts": "Cambios",
    "title": "Páginas",
    "head_skipped": "{n:,} publicaciones saltadas en 10 s",
    "head_dup": "{n:,} repetidas en 10 s",
    "head_deep": "La página {page:,} leyó {rows:,} filas",
    "head_import": "Un solo created_at para cientos de publicaciones",
    "head_viral": "Llueven publicaciones arriba",
    "head_cleanup": "Se borran publicaciones recientes",
    "head_sync": "Procesos recorren el feed entero",
    "head_ok": "{rows:,} publicaciones; cada página lee ~20",
    "note_chart": "Gráfica: tiempo ocupado de la base de datos, % de 4 workers.",
    # los dibujos
    "state_skipping": "SALTANDO",
    "state_repeating": "REPITIENDO",
    "state_scans": "LECTURAS LARGAS",
    "state_import": "CARGA",
    "state_viral": "VIRAL",
    "state_cleanup": "PURGA",
    "state_sync": "SINCRONIZACIÓN",
    "pic_state": "3 APIs → 4 workers · {rows} filas/pág: {state}",
    # errores en tu código
    "stuck": "una página lleva más de {seconds:.0f} s en curso: ¿list_posts() llega a devolver?",
}

LESSON = Lesson(
    title="Paginación por clave",
    one_liner="Pagina por dónde estás (la última clave que mostraste), no por cuántas filas había antes.",
    learn=(
        "LIMIT 20 OFFSET 40 significa \"sáltate las 40 primeras filas, tal como están ahora\". Entre dos "
        "peticiones las filas se mueven: una publicación escrita arriba empuja todo un puesto hacia abajo, y "
        "la página siguiente repite una publicación; una publicación borrada por encima sube todo un puesto, "
        "y otra no se muestra nunca. Nadie recibe un error, solo una lista equivocada.",
        "OFFSET además es lento justo donde duele. La base de datos no puede saltar a la fila 20.000: "
        "recorre el índice desde arriba y tira las 20.000 primeras filas. Un proceso que pagina la tabla "
        "entera lee n^2/2 filas, y sus páginas profundas ocupan workers por los que todos los demás esperan.",
        "La paginación por clave (seek) recuerda dónde está el cliente: la clave de orden de la última "
        "fila que recibió. La página siguiente es WHERE created_at < :ultimo ORDER BY created_at DESC "
        "LIMIT 20. El índice va directo ahí y lee 20 filas, en la página 1 o en la 10.000, y las filas "
        "que se escriben o borran en otra parte no la mueven.",
        "La clave tiene que ser única. Muchas filas pueden compartir created_at (una inserción masiva en "
        "una transacción recibe un solo now()); con < te saltas las que no cupieron en la página, con <= "
        "las vuelves a mostrar. Añade un desempate: ORDER BY created_at DESC, id DESC y WHERE "
        "(created_at, id) < (:t, :id), con un índice en (created_at, id).",
        "Devuelve la clave como un cursor opaco (base64 de un JSON pequeño), para que los clientes no lo "
        "construyan ni lo editen y puedas cambiarlo más adelante; rechaza con un 400 lo que no se pueda "
        "decodificar. Fírmalo (HMAC) si los clientes no deben poder falsificarlo. Guarda valores, no un "
        "puntero: sigue funcionando después de borrarse su fila. No vuelvas a buscar la fila por id.",
    ),
    watch_for=(
        "OFFSET: publicaciones repetidas (morado) cada vez que se escriben otras por encima de los lectores, "
        "saltadas (rojo) cuando se borran, y las páginas del indexador leen miles de filas (naranja oscuro).",
        "Clave created_at: ~20 filas por página y sin repetidas, pero en la carga masiva cada recorrido "
        "que llega al created_at de la carga se salta las publicaciones que no cupieron en su página (rojo).",
        "Clave (created_at, id): nada rojo ni morado, ~20 filas leídas por página, las páginas profundas tan "
        "rápidas como la 1.",
    ),
    build=(
        ("SQL: la consulta por clave y su índice",
         "CREATE INDEX posts_feed ON posts (created_at DESC, id DESC);\n"
         "SELECT id, created_at, body FROM posts\n"
         "WHERE (created_at, id) < ($1, $2)      -- el cursor\n"
         "ORDER BY created_at DESC, id DESC\n"
         "LIMIT 20;"),
        ("Python: un cursor opaco",
         "def encode(post):\n"
         "    data = json.dumps({\"t\": post.created_at, \"id\": post.id}).encode()\n"
         "    return base64.urlsafe_b64encode(data).decode()\n"
         "\n"
         "def decode(cursor):\n"
         "    try:\n"
         "        d = json.loads(base64.urlsafe_b64decode(cursor))\n"
         "        return int(d[\"t\"]), int(d[\"id\"])\n"
         "    except Exception:\n"
         "        raise BadCursor(cursor)   # -> 400"),
        ("HTTP: la página siguiente como enlace",
         "GET /posts?limit=20\n"
         "-> 200 {\"items\": [...], \"next_cursor\": \"eyJ0IjoxNzYw...\"}\n"
         "GET /posts?limit=20&cursor=eyJ0IjoxNzYw...\n"
         "-> 400 cuando el cursor no se puede decodificar"),
    ),
    checklist=(
        "El orden es total: termina con una columna única (el id).",
        "Hay un índice exactamente sobre las columnas de orden, en ese orden.",
        "El cursor guarda los valores de orden de la última fila, no un offset ni solo su id.",
        "La comparación es estricta y cubre todas las columnas de orden: (created_at, id) < (t, id).",
        "Los cursores son opacos para los clientes; uno malo es un 400, nunca un 500 ni otra página.",
        "Las páginas profundas cuestan lo mismo que la 1: mira las filas leídas por página, no solo la latencia.",
        "Con un cursor no se puede saltar a la página 37; ofrece filtros o fechas en su lugar.",
    ),
    refs=(
        Ref("Markus Winand: We need tool support for keyset pagination",
            "https://use-the-index-luke.com/no-offset",
            "Por qué OFFSET es lento e inestable, y el método seek con valores de fila."),
        Ref("Use The Index, Luke: Paging through results",
            "https://use-the-index-luke.com/sql/partial-results/fetch-next-page",
            "El método seek paso a paso, y por qué el orden tiene que ser determinista."),
        Ref("PostgreSQL: LIMIT and OFFSET",
            "https://www.postgresql.org/docs/current/queries-limit.html",
            "Las filas que salta un OFFSET se calculan igualmente dentro del servidor."),
        Ref("PostgreSQL: Row constructor comparison",
            "https://www.postgresql.org/docs/current/functions-comparisons.html",
            "(a, b) < (c, d): cómo se compara una fila, columna a columna."),
        Ref("Slack Engineering: Evolving API pagination at Slack",
            "https://slack.engineering/evolving-api-pagination-at-slack/",
            "Por qué Slack pasó su API de offsets a cursores opacos."),
        Ref("Stripe API: Pagination",
            "https://docs.stripe.com/api/pagination",
            "Paginación con cursor y starting_after: el id del último objeto que recibiste."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/keyset_pagination/es/main.py y mira cómo desaparecen las lecturas "
        "profundas (naranja oscuro) y las repetidas (morado).",
        "Luego mira la primera carga masiva: ¿por qué todavía se saltan publicaciones?",
        "Haz la etapa 2 y ejecuta con --seed 4 para ver una purga: se borra la publicación del propio cursor, "
        "y nada se rompe.",
    ),
)

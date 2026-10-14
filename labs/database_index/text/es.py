"""Laboratorio database_index, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Índices de base de datos"
SUMMARY = "La tabla no deja de crecer y cada consulta la lee entera. Añade los índices que lo arreglan."
PARAMS = {"rate": "logins por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"import": "CARGA", "report": "RANGOS", "spike": "PICO", "calm": "CALMA"}
CAUSES = {
    "partner_import": "un socio importa su lista de usuarios",
    "backfill": "una migración rellena cuentas antiguas",
    "csv_upload": "un administrador sube un CSV enorme",
    "new_dashboard": "se publicó un panel nuevo",
    "finance_export": "finanzas lanza su exportación de fin de mes",
    "ad_hoc_query": "un analista lanza informes a mano",
    "newsletter": "salió el boletín",
    "login_storm": "un bug de la app cierra la sesión de todos",
    "app_release": "una nueva versión de la app",
}

STAGES = [
    StageText("Lectura completa",
              "Reto: cada consulta lee toda la tabla, y no deja de crecer. Indexa los logins.",
              "Etapa 1: un índice hash email -> posición para find_by_email"),
    StageText("Índice hash",
              "Reto: un login lee una fila, pero cada informe por rango sigue leyendo todo.",
              "Etapa 2: un índice compuesto (país, tiempo) con bisect"),
    StageText("Índice hash + compuesto",
              "Resuelto: cada consulta lee solo las filas que devuelve, crezca lo que crezca la tabla.",
              "Todas las etapas hechas"),
]

GOALS = {
    "lookups": GoalText("Filas/login ≤ 5", "indexa email -> posición"),
    "ranges": GoalText("Filas/rango ≤ 2x", "indexa (país, tiempo)"),
    "p99": GoalText("p99 < 100ms", "lee menos filas"),
    "answered": GoalText("Respondidas ≥ 99%", "mantén bien los índices"),
}

LEGEND = {"idle": "en reposo", "cheap": "pocas filas", "costly": "más filas leídas",
          "timed_out": "se rindió", "served": "servida", "limit": "límite", "incident": "incidente"}

STRINGS = {
    # incidentes
    "title_import": "Carga",
    "title_report": "Informe",
    "title_spike": "Pico",
    "start_import": "recibe {rows:,.0f} filas importadas: {cause}",
    "start_report": "lanza {x:.0f}x más consultas por rango: {cause}",
    "start_spike": "recibe {x:.1f}x logins: {cause}",
    "end": "vuelve la calma",
    "warn_slow": "las consultas tardan {ms:.0f} ms",
    "warn_timeouts": "los usuarios se cansan de esperar a la base de datos",
    # valores de los objetivos
    "ratio": "{value:.1f}x",
    "timeouts": "timeouts",
    # el panel
    "tile_lookup": "Login",
    "tile_range": "Rango",
    "tile_p99": "p99",
    "bar_logins": "Logins",
    "bar_ranges": "Rangos",
    "bar_writes": "Escrituras",
    "queries": "Consultas",
    "head_timeouts": "{n} usuarios se cansaron de esperar",
    "head_import": "Carga: la tabla tiene {rows:,} filas",
    "head_report": "Un informe lanza consultas por rango",
    "head_spike": "{x:.1f}x logins",
    "head_calm": "{rows:,} filas; un login lee {read:,.0f}",
    "note_chart": "Gráfica: tiempo ocupado de la BD, % de 4 workers.",
}

LESSON = Lesson(
    title="Índices de base de datos",
    one_liner="Una consulta que lee todas las filas va más lenta a medida que crece la tabla; un índice lee solo lo que necesita.",
    learn=(
        "Sin índice, una base de datos responde con una lectura completa (full scan): lee cada fila y se "
        "queda con las que coinciden. Va bien con 1,000 filas y fatal con 10 millones, y la tabla no deja "
        "de crecer: una consulta rápida el día del lanzamiento se vuelve un poco más lenta cada día.",
        "Un índice hash relaciona un valor con el sitio donde vive su fila (email -> posición). Una "
        "búsqueda por igualdad lee una fila. No sirve para 'entre': un hash no tiene orden.",
        "Un árbol B (aquí: una lista ordenada y bisect) guarda las claves en orden, así que un rango es "
        "una búsqueda de su inicio más un recorrido hasta su fin. Un índice compuesto (país, tiempo) "
        "responde 'este país, en este rango de tiempo' leyendo solo las filas que devuelve. El orden de "
        "las columnas importa: primero las de igualdad, después la del rango.",
        "Los índices no son gratis: cada inserción actualiza todos los índices, y ocupan memoria. Indexa "
        "lo que piden tus consultas y comprueba con EXPLAIN que se usan.",
    ),
    watch_for=(
        "Lectura completa: los logins leen toda la tabla; tras una carga la base de datos se queda atrás y los usuarios se rinden.",
        "Índice hash: un login lee una fila, pero los informes por rango siguen tiñendo la gráfica de naranja.",
        "Índice hash + compuesto: las filas leídas por consulta siguen siendo pocas, sea cual sea el tamaño de la tabla.",
        "La tabla crece en todas las etapas; solo cambia lo que cuesta leerla.",
    ),
    build=(
        ("PostgreSQL: los dos índices de este laboratorio",
         "CREATE UNIQUE INDEX users_email ON users (email);\n"
         "CREATE INDEX users_country_time ON users (country, signed_up_at);"),
        ("Comprueba que una consulta usa su índice",
         "EXPLAIN ANALYZE\n"
         "SELECT * FROM users\n"
         "WHERE country = 'BR' AND signed_up_at >= now() - interval '1 hour';\n"
         "-- busca 'Index Scan using users_country_time', no 'Seq Scan'"),
        ("Python: un índice ordenado con bisect",
         "lo = bisect_left(index, (start, -1))\n"
         "hi = bisect_left(index, (end, -1))\n"
         "rows = [heap.get(pos) for _, pos in index[lo:hi]]"),
    ),
    checklist=(
        "Cada consulta frecuente tiene un índice; compruébalo con EXPLAIN sobre datos del tamaño de producción.",
        "En los índices compuestos, primero las columnas de igualdad y al final la del rango.",
        "Vigila las filas leídas por consulta ('rows examined'), no solo la latencia: avisa antes.",
        "No indexes de más: cada índice cuesta escrituras y memoria.",
        "Haz pruebas de carga con una tabla tan grande como la del año que viene, no la de hoy.",
    ),
    refs=(
        Ref("Use The Index, Luke",
            "https://use-the-index-luke.com/",
            "La indexación en SQL explicada para desarrolladores: árboles B, índices compuestos, rangos (en inglés)."),
        Ref("PostgreSQL: Indexes",
            "https://www.postgresql.org/docs/current/indexes.html",
            "Tipos de índice, índices de varias columnas y cuándo se usan (en inglés)."),
        Ref("PostgreSQL: Using EXPLAIN",
            "https://www.postgresql.org/docs/current/using-explain.html",
            "Leer un plan de consulta: Seq Scan frente a Index Scan, filas y coste (en inglés)."),
        Ref("SQLite: Query Planning",
            "https://www.sqlite.org/queryplanner.html",
            "Cómo usa un planificador un índice para encontrar filas, con dibujos (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/database_index/es/main.py y mira cómo la tarjeta de logins baja a 1 fila.",
        "Haz la etapa 2 y mira cómo los informes dejan de teñir la gráfica de naranja.",
        "Prueba --set rate=60: ¿qué etapa sigue aguantando?",
    ),
)

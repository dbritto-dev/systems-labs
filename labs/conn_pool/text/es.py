"""Laboratorio conn_pool, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Pool de conexiones"
SUMMARY = "Cada petición abre una conexión a la base de datos. Agrúpalas en un pool, ponle tope, falla rápido."
PARAMS = {"rate": "peticiones de usuarios por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"slow": "LENTA", "fast": "RÁPIDA", "spike": "PICO", "calm": "CALMA"}
CAUSES = {
    "autovacuum": "autovacuum está reescribiendo la tabla de pedidos",
    "report_locks": "un informe largo bloquea la tabla de pedidos",
    "backup_disks": "una copia de seguridad satura los discos",
    "dropped_index": "un despliegue borró un índice y las consultas recorren la tabla",
    "marketing_email": "salió un correo de marketing",
    "cron_fanout": "un cron lanza trabajo para cada usuario",
    "mobile_release": "una versión móvil hizo que todas las apps se refrescaran a la vez",
}

STAGES = [
    StageText("Conexión nueva",
              "Reto: cada petición abre y cierra su propia conexión. Reutilízalas en un pool.",
              "Etapa 1: guarda las conexiones liberadas y vuelve a darlas"),
    StageText("Pool",
              "Reto: si la base de datos va lenta, el pool pasa de sus 50 conexiones. Ponle un tope.",
              "Etapa 2: nunca abras más de max_size; espera a que se libere una"),
    StageText("Pool acotado",
              "Reto: con tope, pero las peticiones esperan conexión durante segundos. Ríndete antes.",
              "Etapa 3: lanza PoolTimeout tras timeout segundos"),
    StageText("Pool acotado + timeout",
              "Resuelto: las conexiones se reutilizan, con tope bajo el límite, y las esperas son cortas.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "el pool debe dar conexiones"),
    "reuse": GoalText("Reuso ≥ 90%", "guarda las conexiones libres"),
    "errors": GoalText("Errores conex. = 0", "limita el pool a max_size"),
    "wait": GoalText("Espera p99 < 1s", "lanza PoolTimeout antes"),
    "recovered": GoalText("Recuperado ≥ 95%", "da conexiones a quien espera"),
}

LEGEND = {"idle": "en reposo", "query": "consulta", "waits": "espera conexión", "opens": "abre conexión",
          "failed": "fallida", "served": "servida", "idle_conn": "conexión libre", "limit": "límite",
          "incident": "incidente"}

STRINGS = {
    # incidentes
    "slowdown": "Lentitud",
    "spike": "Pico",
    "is_slow": "va lenta: {cause}",
    "fast_again": "vuelve a ir rápida",
    "gets_traffic": "recibe {times:.0f}x de tráfico: {cause}",
    "traffic_normal": "el tráfico vuelve a la normalidad",
    "warn_refused": "demasiadas conexiones: {n:.0f} rechazadas",
    "warn_wait": "hay peticiones que esperan más de 1 s",
    # el panel
    "tile_reuse": "Reuso",
    "tile_conns": "Conex.",
    "tile_wait": "Esp. p99",
    "toplist": "Peticiones",
    "bar_ask": "Piden",
    "bar_served": "Servidas",
    "bar_failed": "Fallidas",
    "head_refused": "Demasiadas conexiones: {n} rechazadas",
    "head_fail_fast": "Falla rápido: {n} dejaron de esperar",
    "head_waiting": "{n} peticiones esperan una conexión",
    "head_slow_ok": "La base de datos va lenta; el pool aguanta",
    "head_spike_ok": "Pico de tráfico; el pool aguanta",
    "head_pool": "Pool: {n} conexiones abiertas",
    "limit_max": "{n} máx",
    "note_chart": "El gráfico: conexiones abiertas (ocupadas, libres).",
    # errores en tu código
    "closed": "consulta sobre una conexión cerrada",
    "too_many": "demasiadas conexiones ({n} abiertas)",
    "stuck": "una petición lleva más de {seconds:.0f} s esperando conexión: "
             "¿release() despierta a las peticiones que esperan en acquire()?",
}

LESSON = Lesson(
    title="Pool de conexiones",
    one_liner="Abrir una conexión a la base de datos es lento y la base de datos solo admite unas pocas. Agrúpalas en un pool, ponle tope, falla rápido.",
    learn=(
        "Abrir una conexión a la base de datos es caro: un handshake TCP y TLS, autenticación y, en "
        "PostgreSQL, todo un proceso nuevo en el servidor. Una consulta sobre una conexión abierta tarda "
        "unos milisegundos. Abrir una por petición multiplica el trabajo y la latencia.",
        "Un pool mantiene abiertas las conexiones liberadas y se las da a la siguiente petición. Así la "
        "mayoría de las peticiones no pagan nada por conectarse.",
        "Un pool sin límite crece con la demanda. Cuando la base de datos va lenta, las peticiones "
        "retienen las conexiones más tiempo, el pool abre más y llega al max_connections de la base de "
        "datos: las peticiones nuevas se rechazan. Más conexiones tampoco dan más rendimiento: pasado el "
        "número de núcleos, todo va más lento.",
        "Un pool acotado pone un tope por debajo del límite y hace que las peticiones esperen a una "
        "conexión libre. Eso protege la base de datos, pero si sigue lenta la cola de peticiones que "
        "esperan crece sin fin.",
        "Un timeout al pedir conexión acota la espera: pasado ese tiempo la petición falla rápido y quien "
        "llama puede reintentar, degradar o mostrar un error, en vez de amontonarse detrás de la cola.",
    ),
    watch_for=(
        "Conexión nueva: todos los puntos son naranja oscuro (abriendo conexión) y una lentitud llega al límite de 50.",
        "Pool: los puntos blancos reutilizan conexiones, pero la lentitud sigue llevando el pool a 50 y rechaza peticiones.",
        "Pool acotado: no hay rechazos, pero los usuarios esperan en naranja, cada vez más mientras va lenta.",
        "Pool acotado + timeout: las esperas se cortan en 0.5 s; algunas peticiones fallan rápido mientras va lenta.",
    ),
    build=(
        ("Python: el pool que trae asyncpg",
         "pool = await asyncpg.create_pool(dsn, min_size=5, max_size=20)\n"
         "async with pool.acquire(timeout=0.5) as conn:   # lanza TimeoutError si no hay ninguna libre\n"
         "    rows = await conn.fetch(\"SELECT ...\")"),
        ("Java: HikariCP",
         "config.setMaximumPoolSize(20);\n"
         "config.setConnectionTimeout(500);   // ms de espera por una conexión antes de fallar"),
        ("PostgreSQL: un pooler delante de muchos servidores de aplicación (PgBouncer)",
         "[pgbouncer]\n"
         "pool_mode = transaction\n"
         "default_pool_size = 20\n"
         "max_client_conn = 1000"),
    ),
    checklist=(
        "Suma max_size de todas las instancias de la aplicación; que quede por debajo del max_connections de la base de datos.",
        "Dimensiona los pools según los núcleos de la base de datos, no según el tráfico (los pools pequeños suelen ir más rápido).",
        "Pon un timeout para pedir conexión, más corto que el plazo de la petición.",
        "Métricas: conexiones abiertas, en uso y en espera; tiempo de espera para obtener una; conexiones rechazadas.",
        "¿Muchos servidores de aplicación? Pon un pooler (PgBouncer, RDS Proxy) entre ellos y la base de datos.",
    ),
    refs=(
        Ref("HikariCP: About Pool Sizing",
            "https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing",
            "Por qué un pool pequeño gana a uno grande: núcleos, discos y contención (en inglés)."),
        Ref("PostgreSQL: Connections and Authentication",
            "https://www.postgresql.org/docs/current/runtime-config-connection.html",
            "max_connections, y lo que le cuesta al servidor cada conexión (en inglés)."),
        Ref("Brandur: Managing Postgres connection limits",
            "https://brandur.org/postgres-connections",
            "Por qué las conexiones de Postgres son caras, y cómo agruparlas con PgBouncer (en inglés)."),
        Ref("PgBouncer: features",
            "https://www.pgbouncer.org/features.html",
            "Pooling por sesión, transacción y sentencia delante de PostgreSQL (en inglés)."),
        Ref("AWS: Amazon RDS Proxy",
            "https://aws.amazon.com/rds/proxy/",
            "Un pooler gestionado que comparte conexiones entre muchos clientes (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/conn_pool/es/main.py y mira cómo desaparece el naranja oscuro (conexiones nuevas).",
        "Haz la etapa 2 y mira cómo paran los rechazos, mientras las esperas crecen durante una lentitud.",
        "Haz la etapa 3 y mira cómo la espera p99 se queda por debajo de 1 s.",
        "Prueba max_size=50 en Pool: ¿un pool más grande hace que la lentitud pase antes?",
    ),
)

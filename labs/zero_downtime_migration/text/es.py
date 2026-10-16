"""Laboratorio zero_downtime_migration, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Migración sin caída"
SUMMARY = "Renombra una columna mientras instancias viejas y nuevas comparten la base de datos. Expande, rellena, contrae."
PARAMS = {"rate": "peticiones de usuarios por segundo", "rows": "filas de la tabla users"}

INCIDENT = IncidentText("Migración", "la migración", "la próxima migración")
VERBS = {"open": "INICIO", "close": "FIN", "deploy": "LANZA", "revert": "ATRÁS", "resume": "AVANZA",
         "final": "FINAL", "add": "AÑADE", "rename": "CAMBIA", "drop": "BORRA", "copied": "COPIA",
         "reads": "LEE", "writes": "GRABA", "lag": "ATRASO", "busy": "CARGA", "out": "FUERA", "back": "VUELVE",
         "done": "HECHO", "stop": "CORTE", "fail": "FALLA"}
CAUSES = {
    "weekly_release": "la versión semanal",
    "feature_launch": "el lanzamiento de una función",
    "hotfix": "un parche urgente que también ordena el esquema",
    "canary_alarm": "una alarma del canario por la latencia del pago",
    "error_spike": "un pico de errores en un servicio ajeno",
    "bad_config": "una opción de configuración que parecía mal",
    "analytics_query": "una consulta analítica larga en la réplica",
    "replica_disk": "el disco de la réplica saturado por una instantánea",
    "network_blip": "un corte breve de red entre las zonas",
    "traffic_peak": "un pico de tráfico por un correo promocional",
    "nightly_job": "la tarea nocturna de facturación",
    "cache_flush": "una caché vaciada que manda cada lectura a la base de datos",
}

STAGES = [
    StageText("Renombrar de golpe",
              "Reto: la columna se renombra de golpe y cada instancia vieja falla hasta que la cambian.",
              "Etapa 1: expandir/contraer (escribe ambas, borra al final)"),
    StageText("Expandir/contraer",
              "Reto: sin errores, pero una gran copia bloquea escrituras y pierde las de la vuelta atrás.",
              "Etapa 2: backfill() por lotes, verify()"),
    StageText("Relleno frenado y verificado",
              "Resuelto: el cambio de nombre se despliega sin errores, rápido y sin nombres viejos.",
              "Todas las etapas hechas"),
]

GOALS = {
    "errors": GoalText("Errores = 0", "deja la vieja hasta el final"),
    "p99": GoalText("p99 escr. <40ms", "lotes y pausa si hay carga"),
    "wrong": GoalText("Erróneos = 0", "doble escritura; verify()"),
    "done": GoalText("Hecha en ≤60s", "borra la columna vieja"),
}

LEGEND = {"idle": "en reposo", "waiting": "esperando", "slow": "escritura > 40 ms", "served": "servida",
          "failed": "fallida", "wrong": "nombre erróneo", "backfill": "copiando", "trouble": "atraso o carga"}

STRINGS = {
    "note_dots": "Los puntos son una muestra, más lentos (decorativo).",
    "note_chart": "La gráfica: la carga de la base de datos, %: la app (blanco), otro trabajo (naranja), tus copias (morado).",
    # la ventana
    "open": "la próxima versión renombra users.{old} → {new}",
    "open_cause": "{cause} renombra users.{old} → {new}",
    "closed": "se cierra la ventana de migración",
    "not_done": "sin hacer",
    # sus pasos (eventos)
    "step_deploy": "v{v} se despliega",
    "step_rollback": "revertida a medias: {cause}",
    "step_forward": "v{v} vuelve a avanzar",
    "step_released": "v{v} es definitiva",
    "step_add": "{col} añadida (NULL)",
    "step_rename": "{col}",
    "step_drop": "{col} borrada",
    "step_copied": "cada fila en {new}",
    "step_read_new": "lee de {new}",
    "step_read_old": "lee de {old}",
    "step_write_new": "deja de escribir {old}",
    "step_write_both": "vuelve a escribir {old}",
    "step_lag_start": "la réplica se atrasa: {cause}",
    "step_lag_end": "la réplica se puso al día",
    "step_peak_start": "la base de datos se carga: {cause}",
    "step_peak_end": "la base de datos está tranquila",
    "step_shunned": "réplica {lag:.0f}s atrás: fuera",
    "step_back_in": "la réplica vuelve al grupo",
    "step_done": "migrada en {s:.0f} s",
    "step_unfinished": "{old} sigue ahí",
    "step_failed": "{why}",
    "step_cut": "migrate quedó a medias",
    "err_missing": "no existe {col}",
    "err_exists": "{col} ya existe",
    # el estado bajo los dibujos
    "state_old": "SOLO {old}",
    "state_both": "AMBAS · {pct:.0f}% COPIADO",
    "state_new": "SOLO {new}",
    "state_failing": "{n} FALLAN/s",
    "cluster_state": "v{va}: {na} · v{vb}: {nb} · atraso {lag:.1f}s",
    "cluster_copied": " · copiado {pct:.0f}%",
    # el dibujo de relevo: las instancias en cada versión, bajo la flota
    "relay_fleet": "v{va}:{na} v{vb}:{nb}",
    "relay_copied": "{pct:.0f}% COPIADO",
    # el panel
    "tile_errors": "Errores",
    "tile_p99": "p99",
    "tile_wrong": "Erróneos",
    "bars": "Columnas",
    "bars_sub": "en el último segundo",
    "bar_old": "vieja",
    "bar_new": "nueva",
    "bar_failed": "fallidas",
    "stat_wrong": "erróneos",
    "stat_write_p99": "p99 escritura",
    "limit": "p99 escritura > 40ms",
    "head_errors": "Las instancias viejas fallan",
    "head_slow": "Las escrituras esperan al relleno",
    "head_shunned": "Réplica fuera: lecturas al primario",
    "head_wrong_reads": "Las lecturas dan nombres viejos",
    "head_calm": "Todas las instancias en una versión",
    "head_copying": "Relleno: {pct:.0f}% de las filas copiadas",
    "head_stale": "{n} filas cambiaron tras su copia",
    "head_done": "Migrada: {old} → {new}",
    "head_paused": "Base de datos cargada: el relleno espera",
    "head_mixed": "v{va} en {old}, v{vb} en {new} instancias",
    "head_window": "Migrando users.{old} → {new}",
    # errores en tu código
    "stuck": "una petición lleva más de {seconds:.0f} s: ¿read_name o write_name espera algo que nunca termina?",
}

LESSON = Lesson(
    title="Migración sin caída",
    one_liner="Nunca cambies una columna en un solo paso: expande, migra los datos y el código, y luego contrae.",
    learn=(
        "Un despliegue gradual reemplaza las instancias de la app de una en una, así que durante un rato la "
        "versión vieja y la nueva atienden tráfico a la vez, sobre la misma base de datos. Si la migración "
        "renombra users.fullname a display_name de golpe, cada instancia vieja que sigue en marcha falla "
        "con una columna que ya no existe; una vuelta atrás reinstala instancias que fallan. Cada cambio "
        "de esquema debe funcionar con las dos versiones.",
        "Expandir/contraer (cambio en paralelo): añade la columna nueva (al instante: NULL, sin valor por "
        "defecto que escribir), haz que la versión nueva escriba ambas columnas en una sola sentencia y siga "
        "leyendo la vieja, rellena la nueva para las filas escritas antes (el relleno), pasa las lecturas a "
        "ella, deja de escribir la vieja y bórrala al final, cuando ya no pueda volver ninguna versión que la "
        "necesite.",
        "El relleno es la parte peligrosa. Un solo UPDATE de todas las filas las bloquea todas hasta que "
        "se consolida, así que las escrituras esperan segundos, carga la base de datos e inunda la réplica. "
        "Copia en lotes pequeños, haz una pausa entre ellos y detente mientras la base de datos esté cargada "
        "o la réplica atrasada: herramientas como gh-ost y pt-online-schema-change se frenan justo así.",
        "Una copia solo es correcta para las filas que nadie cambia después a través de la columna vieja "
        "sola. Hasta que la versión es definitiva, una vuelta atrás reinstala instancias viejas que solo "
        "escriben la columna vieja, así que verifica antes de cambiar: compara las dos columnas lote a lote, "
        "vuelve a copiar lo que difiere, y solo entonces lee la nueva y borra la vieja.",
    ),
    watch_for=(
        "Renombrar de golpe: la puerta se cierra en rojo y los errores suben mientras hay instancias viejas, y otra vez al revertir.",
        "Expandir/contraer: sin errores, pero la copia tiñe de morado la gráfica, el p99 llega a segundos y quedan nombres erróneos.",
        "Relleno frenado y verificado: la carga morada no pasa la línea discontinua; verify arregla las filas viejas.",
    ),
    build=(
        ("Rails (strong_migrations): renombrar una columna por pasos",
         "add_column :users, :display_name, :string      # 1 expandir\n"
         "# 2 despliegue: escribe ambas, lee fullname\n"
         "User.in_batches(of: 1000) { |b| b.update_all('display_name = fullname'); sleep(0.1) }\n"
         "# 3 despliegue: lee display_name; 4 despliegue: deja de escribir fullname\n"
         "remove_column :users, :fullname                  # 5 contraer"),
        ("PostgreSQL: un lote del relleno, con un timeout de bloqueo",
         "SET lock_timeout = '2s';\n"
         "UPDATE users SET display_name = fullname\n"
         " WHERE id >= 4000 AND id < 4100\n"
         "   AND display_name IS DISTINCT FROM fullname;"),
        ("gh-ost (MySQL): copia filas por trozos, frenando por carga y atraso de la réplica",
         "gh-ost --alter='ADD COLUMN display_name VARCHAR(255)' \\\n"
         "  --chunk-size=1000 --max-load=Threads_running=25 \\\n"
         "  --max-lag-millis=1500 --throttle-control-replicas=replica1 --execute"),
    ),
    checklist=(
        "Cada migración funciona con la versión anterior y con la siguiente (corren a la vez).",
        "Añade columnas que admitan NULL o con un valor constante; nunca renombres ni borres en la misma versión.",
        "Escribe ambas columnas en una sentencia hasta que la vieja desaparezca; lee la vieja hasta verificar.",
        "Rellena en lotes pequeños con una pausa, y detente mientras la carga o el atraso de la réplica sean altos.",
        "Verifica (compara vieja y nueva) cuando la versión sea definitiva; borra la columna vieja al final.",
    ),
    refs=(
        Ref("Stripe: Online migrations at scale",
            "https://stripe.com/blog/online-migrations",
            "Doble escritura, relleno, cambio de lecturas y retirada de los datos viejos, a la escala de Stripe (en inglés)."),
        Ref("Martin Fowler: Parallel Change",
            "https://martinfowler.com/bliki/ParallelChange.html",
            "Expandir, migrar, contraer: cambiar una interfaz en tres fases (en inglés)."),
        Ref("gh-ost: Throttle",
            "https://github.com/github/gh-ost/blob/master/doc/throttle.md",
            "Cómo una herramienta de migración real pausa su copia por carga y por atraso de la réplica (en inglés)."),
        Ref("strong_migrations",
            "https://github.com/ankane/strong_migrations",
            "Qué cambios de esquema no son seguros en Postgres y MySQL, y la forma segura de hacer cada uno (en inglés)."),
        Ref("PlanetScale: Backward compatible database changes",
            "https://planetscale.com/blog/backward-compatible-databases-changes",
            "Los seis pasos de un cambio de nombre seguro, y por qué está cada uno (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/zero_downtime_migration/es/main.py y mira cómo los errores siguen en 0 durante la vuelta atrás.",
        "Haz la etapa 2 y mira cómo el p99 y la carga morada se quedan bajo la línea discontinua.",
        "Pon BATCH = 2000 en tu archivo: ¿por qué ahora una réplica atrasada tumba todo el grupo?",
        "Sáltate verify(): ¿qué migraciones dejan nombres erróneos, y por qué solo esas?",
    ),
)

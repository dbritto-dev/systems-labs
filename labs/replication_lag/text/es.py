"""Laboratorio replication_lag, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Retraso de réplicas"
SUMMARY = "Las lecturas van a réplicas que se retrasan. Que cada usuario vea lo suyo y nada retroceda."
PARAMS = {"rate": "operaciones de usuarios por segundo (15% escrituras)"}

INCIDENT = IncidentText("Retraso", "el retraso", "el próximo retraso")
VERBS = {"lag": "RETRAS", "caught": "AL DÍA", "down": "CAÍDA", "up": "VUELVE", "spike": "PICO", "calm": "CALMA"}
CAUSES = {
    "analytics_query": "una consulta analítica larga frena la réplica",
    "autovacuum": "autovacuum reescribe una tabla grande en la réplica",
    "brownout": "una degradación de red ralentiza la replicación",
    "kernel_patch": "un parche del kernel reinicia la réplica",
    "oom_kill": "la réplica se quedó sin memoria y se reinició",
    "bulk_import": "una importación masiva inunda de escrituras el primario",
    "marketing_email": "un correo de marketing hace que todos actualicen su perfil",
}

STAGES = [
    StageText("Cualquier réplica",
              "Reto: los usuarios no ven sus cambios y las páginas retroceden. Lee tus escrituras.",
              "Etapa 1: lee solo de réplicas que ya tengan tu escritura"),
    StageText("Lee tus escrituras",
              "Reto: cada usuario ve lo suyo, pero las páginas aún retroceden. Que nada vuelva atrás.",
              "Etapa 2: nunca leas algo más viejo que lo ya visto"),
    StageText("Lecturas monótonas",
              "Resuelto: cada uno ve lo suyo, nada retrocede y las réplicas atienden las lecturas.",
              "Todas las etapas hechas"),
]

GOALS = {
    "ryw": GoalText("Propias = 0", "guarda el LSN de cada sesión"),
    "mono": GoalText("Retrocesos = 0", "guarda las versiones vistas"),
    "primary": GoalText("Primario ≤ 35%", "elige una réplica al día"),
}

LEGEND = {"fresh": "al día", "behind": "retrasada", "down": "caída", "read": "lectura",
          "replication": "escritura / réplica", "wrong": "lectura mala", "limit": "límite del primario"}

STRINGS = {
    # incidentes
    "title_restart": "Reinicio",
    "title_spike": "Pico de escrituras",
    "behind": "{name} se retrasa {lag:.0f} s: {cause}",
    "caught_up": "{name} se puso al día",
    "restarts": "{name} se reinicia: {cause}",
    "back": "{name} vuelve y se pone al día",
    "spike": "todas las réplicas se retrasan: {cause}",
    "spike_over": "las réplicas se pusieron al día",
    "warn_ryw": "un usuario no vio su propia escritura",
    "warn_mono": "una página retrocedió en el tiempo",
    # el panel
    "tile_ryw": "Propias",
    "tile_mono": "Atrás",
    "tile_primary": "Primario",
    "bar_replicas": "Réplicas",
    "bar_primary": "Primario",
    "bar_writes": "Escrituras",
    "reads": "Lecturas",
    "head_behind": "{name} va {lag:.1f} s por detrás",
    "head_down": "{name} se está reiniciando",
    "head_spike": "Todas las réplicas ~{lag:.1f} s atrás",
    "head_wrong": "{n} lecturas mal en 5 s",
    "head_ok": "Réplicas a menos de {lag}",
    "note": "Lecturas a cámara lenta; escrituras a su retraso real.",
    # errores en tu código
    "bad_pick": "Router.pick devolvió {name!r}: usa 'primary' o una de r1..r{last}",
    "stuck": "una lectura lleva más de {seconds:.0f} s esperando",
}

LESSON = Lesson(
    title="Retraso de réplicas",
    one_liner="Las réplicas de lectura van un poco por detrás del primario, y a veces mucho. Enruta las lecturas para que nadie lo note.",
    learn=(
        "Replicación asíncrona: una escritura se confirma en el primario y llega a cada réplica un momento "
        "después (milisegundos normalmente, segundos si una réplica está ocupada, reiniciándose o inundada). "
        "Una lectura en una réplica devuelve los datos según su posición en el log (su LSN).",
        "Lee tus escrituras (read your writes): justo después de que un usuario cambia algo, una réplica "
        "puede no tenerlo aún, y el usuario cree que su cambio se perdió. Guarda la posición en el log de la "
        "última escritura de cada sesión y lee solo de una réplica que ya la haya aplicado (o del primario).",
        "Lecturas monótonas (monotonic reads): si dos lecturas de la misma página caen en dos réplicas, la "
        "segunda puede ser más vieja que la primera y la página retrocede en el tiempo. Guarda la versión "
        "más nueva que la sesión ha visto y nunca leas de una réplica que vaya por detrás de ella.",
        "Las dos son garantías de sesión: cuestan un poco de contabilidad por sesión, dejan casi todas las "
        "lecturas en las réplicas y no necesitan coordinación entre réplicas.",
    ),
    watch_for=(
        "Cualquier réplica: puntos rojos en la réplica retrasada: usuarios que no ven lo suyo, páginas que retroceden.",
        "Lee tus escrituras: la tarjeta 'Propias' sigue verde, pero 'Atrás' se pone roja mientras una réplica se retrasa.",
        "Lecturas monótonas: la réplica retrasada no recibe lecturas hasta ponerse al día; el primario recibe pocas.",
        "Las escrituras avanzan despacio hacia una réplica retrasada: esos puntos son su cola pendiente.",
    ),
    build=(
        ("PostgreSQL: la posición que ha reproducido una réplica",
         "-- en el primario, tras escribir:  SELECT pg_current_wal_lsn();\n"
         "-- en una réplica:                 SELECT pg_last_wal_replay_lsn();\n"
         "-- lee de la réplica solo si su LSN reproducido >= el LSN de la sesión"),
        ("Token de sesión en una cookie (cualquier lenguaje)",
         "after_write:  session['lsn'] = db.primary.current_lsn()\n"
         "on_read:      replica = pick(r for r in replicas if r.lsn >= session['lsn'])\n"
         "              session['lsn'] = max(session['lsn'], version_read)"),
    ),
    checklist=(
        "Conoce el retraso de tus réplicas: grafícalo por réplica y alerta en segundos, no solo en 'réplica arriba'.",
        "Lee tus escrituras para quien escribió (LSN de sesión, o leer del primario unos segundos).",
        "Lecturas monótonas dentro de una sesión (réplica fija, o la versión más nueva vista).",
        "Saca automáticamente una réplica retrasada del grupo de lectura; devuélvela cuando se ponga al día.",
        "Acota la antigüedad del resto y dilo en la API ('puede tener hasta 2 s de antigüedad').",
    ),
    refs=(
        Ref("Jepsen: Read Your Writes",
            "https://jepsen.io/consistency/models/read-your-writes",
            "La garantía de sesión, definida con precisión (en inglés)."),
        Ref("Jepsen: Monotonic Reads",
            "https://jepsen.io/consistency/models/monotonic-reads",
            "Nunca ver un estado más viejo tras uno más nuevo (en inglés)."),
        Ref("Werner Vogels: Eventually Consistent",
            "https://www.allthingsdistributed.com/2008/12/eventually_consistent.html",
            "Lee tus escrituras, lecturas monótonas y consistencia de sesión en la práctica (en inglés)."),
        Ref("PostgreSQL: Hot Standby",
            "https://www.postgresql.org/docs/current/hot-standby.html",
            "Leer de réplicas, el retraso de reproducción y sus compromisos (en inglés)."),
        Ref("Amazon Aurora: replication",
            "https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.Replication.html",
            "El retraso de réplicas en una base de datos gestionada y cómo enrutar lecturas (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/replication_lag/es/main.py y mira cómo la tarjeta 'Propias' se pone verde.",
        "Después espera un retraso: ¿qué pasa con la tarjeta 'Atrás'?",
        "Haz la etapa 2 y mira cómo la réplica retrasada no recibe lecturas hasta ponerse al día.",
    ),
)

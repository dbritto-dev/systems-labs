"""La pantalla, en español. Mismos nombres y {placeholders} que en.py (un test lo comprueba)."""

# ---- la ventana
TOO_SMALL = "La terminal mide {cols}x{rows}; hace falta al menos {min_cols}x{min_rows} (se ve mejor en {best}). Agranda la ventana."
PAUSED = "en pausa"
SIMULATING = "simulando"
LOADING = "cargando"
STOPPED = "detenido"
BEHAVIOR = "Ahora:"
EDIT_AND_SAVE = "Edita {file} y guarda: esta ventana lo vuelve a ejecutar."
ERROR = "error: {error}"
MENU = {"pause": "pausa/sigue", "restart": "reinicia", "rerun": "repite", "view": "vista", "quit": "sal"}
VIEW = "vista: {name}"
HUD = "fotograma {ms:.1f} ms · {fps:.0f} fps · dibujó {drawn}/{ticks} · {ahead:.0f} s por delante"  # tecla d
VIEWS = {"lanes": "carriles", "cluster": "clúster", "relay": "relevo", "fanout": "abanico"}
NO_VIEW = "{lab} no tiene la vista {name!r} (tiene: {views})"

# ---- el dibujo: el estado bajo el servidor o el clúster
STATES = {"healthy": "SANO", "down": "CAÍDO", "degraded": "DEGRADADO", "busy": "OCUPADO",
          "overloaded": "SATURADO", "connected": "CONECTADO", "partitioned": "PARTICIONADO"}

# ---- carga y errores
STARTING = "Arrancando {title}"
STEP_PROCESS = "Proceso de Python listo para tu código"
STEP_LOADED = "Cargado {file}"
STEP_SIMULATING = "Simulando el primer minuto con un reloj virtual"
STEP_WHAT = "llegan usuarios, algo falla al azar, se evalúan los objetivos"
WHILE_YOU_WAIT = "Mientras esperas"
WATCH_FOR = "Fíjate en: {text}"
STILL_SIMULATING = "Sigue simulando tras {seconds} s: ¿un bucle lento en tu código? Se detiene a los 20 s."
STOPPED_WITH_ERROR = "Tu código se detuvo con un error"
EDIT = "Edita"
FIX_AND_SAVE = "Corrígelo y guarda: esta ventana lo vuelve a ejecutar."
EDIT_HERE = "edita {where}"
RUN_CRASHED = "la ejecución falló (código de salida {code})"
NO_RESULT = "sin resultado tras {seconds} s, así que se detuvo. ¿Hay un bucle sin fin (reintentos sin límite)?"

# ---- línea de estado
RUNNING_YOUR_CODE = "ejecutando tu código…"
LOADING_YOUR_CODE = "cargando tu código"
SIMULATING_FIRST_MINUTE = "simulando el primer minuto"
RERAN_AT = "{reason} a las {clock}: desde 0:00"
REASONS = {"reran": "repetido", "restarted": "reiniciado"}

# ---- el panel
STATS = {"served": "servidos", "failed": "fallidos", "waiting": "esperando", "p50": "p50", "p99": "p99"}
USERS = "Usuarios"
WAITS = "esperas: últimos 5 s"
CALLS = "Llamadas"
PER_SECOND = "por segundo, último 1 s"
EVENTS = "Eventos"
SO_FAR = "{n} hasta ahora"
NONE_YET = "ninguno aún"
NEXT = "SIG."
STATUS = {"ok": "OK", "alert": "ALERTA", "wait": "ESPERA"}
COUNTS = {"ok": "{n} OK", "alert": "{n} ALERTA", "wait": "{n} ESPERA"}
PHASES = {"before": "antes", "during": "durante", "after": "después"}
VERBS = {"alert": "ALERTA", "ok": "OK", "warn": "AVISO"}  # 6 letras como máximo

# ---- objetivos e incidentes
NEXT_FIRST_RUN = "esperando la primera ejecución"
NEXT_INCIDENT = "esperando {incident}"  # incident: "la próxima caída"
NEXT_AT_START = "{rule}: se evalúa cuando empieza {incident}"
NEXT_AT_END = "{rule}: se evalúa cuando termina {incident}"
NEXT_AFTER = "{rule}: se evalúa después de {incident}"
# lo mismo, corto, para cuando la línea de arriba no cabe en el panel
NEXT_AT_START_SHORT = "{rule} · inicio"
NEXT_AT_END_SHORT = "{rule} · fin"
NEXT_AFTER_SHORT = "{rule} · después"
NEXT_INCIDENT_SHORT = "{incident}"
INCIDENT_TITLE = "{name} n.º {n}"
STARTED = "empezó"
ENDED = "terminó"

# ---- la línea de comandos
LABS_HEADER = "Laboratorios (abre uno con: uv run python -m live <lab>)"
NO_LAB = "no hay un laboratorio llamado {name!r}. Laboratorios: {labs}"
LESSON = {"learn": "Aprende", "watch": "Fíjate en", "build": "En producción", "checklist": "Lista de comprobación",
          "refs": "Para leer más", "next": "Prueba después"}

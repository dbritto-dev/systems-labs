"""Laboratorio canary_releases, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Despliegues canario"
SUMMARY = "Publica versiones nuevas sin riesgo. Primero un canario fijo, luego uno por etapas comparado con la base."
PARAMS = {"rate": "peticiones de usuarios por segundo (deriva ±15%)"}

INCIDENT = IncidentText("Despliegue", "el despliegue", "el próximo despliegue")
VERBS = {"deploy": "NUEVA", "close": "CIERRA", "step": "SUBE", "full": "TOTAL", "rollback": "ATRÁS",
         "cancel": "ANULA", "manual": "MANUAL"}
CAUSES = {
    # versiones buenas: qué cambian
    "copy_change": "textos nuevos en la página de pago",
    "dependency_bump": "una biblioteca actualizada",
    "refactor": "una reorganización del código de búsqueda",
    "flag_cleanup": "se quitan interruptores de funciones viejos",
    # una dependencia falla a ratos mientras sale una versión buena
    "db_failover": "la base de datos conmuta a su réplica",
    "dns_blip": "el resolvedor DNS pierde consultas de vez en cuando",
    "provider_slow": "el proveedor de pagos tiene un mal minuto",
    "cache_restart": "la caché compartida se reinicia, nodo a nodo",
    # bucles de caídas
    "missing_env": "necesita un ajuste que no está en producción: se cae y reinicia sin parar",
    "bad_config": "una errata en su configuración: se cae al arrancar, una y otra vez",
    "oom_start": "se queda sin memoria al arrancar: se cae y reinicia sin parar",
    "schema_mismatch": "espera una columna que la base de datos aún no tiene: se cae sin parar",
    # regresiones de errores sutiles
    "edge_case": "un caso límite sin tratar: falla ~3% de las peticiones",
    "short_timeout": "un timeout de cliente demasiado corto: falla ~3% de las peticiones",
    "retry_removed": "un reintento quitado por error: falla ~3% de las peticiones",
    "serializer": "un serializador nuevo se atraganta con algunos registros: falla ~3%",
    # regresiones de latencia
    "n_plus_one": "una consulta N+1 nueva: un cuarto de las peticiones va más lento",
    "sync_logging": "registros síncronos en un camino caliente: un cuarto de las peticiones va más lento",
    "cache_key": "un fallo en la clave de caché: un cuarto de las peticiones no acierta en la caché",
    "regex": "una expresión regular que retrocede: un cuarto de las peticiones va más lento",
    # fallos en una sola ruta
    "currency_rounding": "un cambio de redondeo rompe los pagos en una moneda (/pay)",
    "coupon_parser": "el lector de cupones rechaza cupones válidos (/pay)",
    "tax_rule": "una regla de impuestos nueva falla en algunas regiones (/pay)",
    "card_validation": "una validación de tarjetas más estricta rechaza tarjetas válidas (/pay)",
}

STAGES = [
    StageText("Todo a la vez",
              "Reto: cada versión llega a todos los usuarios a la vez; una mala los daña a todos.",
              "Etapa 1: un canario del 5%, un límite fijo, un tiempo fijo"),
    StageText("Canario fijo",
              "Reto: las reglas fijas dejan pasar una versión lenta y revierten buenas por ruido.",
              "Etapa 2: compara con la base; 5→25→50→100%"),
    StageText("Canario por etapas",
              "Resuelto: cada etapa se compara con la base con datos suficientes; las malas se revierten.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "decide() debe dar de 0 a 1"),
    "hurt": GoalText("Dañadas ≤ 0.5%", "empieza poco: un canario 5%"),
    "full": GoalText("Mala al 100% = 0", "compara errores Y latencia"),
    "alarms": GoalText("Falsa alarma = 0", "compara con la base"),
    "rollout": GoalText("Despliegue ≤ 90s", "sube 5→25→50→100%"),
}

LEGEND = {"idle": "en reposo", "request": "petición", "waits": "espera", "served": "servida", "failed": "fallida",
          "live": "versión activa", "canary": "versión nueva (canario)", "slow": "respuesta lenta",
          "incident": "despliegue"}

STRINGS = {
    "note_dots": "Los puntos son una muestra, más lentos (decorativo).",
    "note_chart": "Gráfica: peticiones por segundo según la versión que respondió; lentas o fallidas encima.",
    # los dibujos
    "state_live": "ACTIVA v{v}",
    "state_canary": "CANARIO v{v} {w:.0%}",
    "state_bad": "VERSIÓN MALA ACTIVA v{v}",
    "state_back": "REVERTIDA v{v}",
    "cluster_live": "{state}  · v{v} en las {n} instancias",
    "cluster_canary": "{state} en {b} de {n} · v{live} en {a}",
    # el dibujo de relevo: lo que hace el enrutador, las instancias de cada versión
    "relay_split": "{w:.0%} → v{v}",
    "relay_router": "enrutador",
    "relay_fleet": "v{v} en {b}/{n}",
    "relay_bad": "MALA v{v}",
    "relay_back": "REVERTIDA v{v}",
    # despliegues
    "good": "Versión buena",
    "flaky": "Dependencia inestable",
    "crash": "Caídas en bucle",
    "errors": "Regresión de errores",
    "latency": "Versión lenta",
    "segment": "Fallo en /pay",
    "good_start": "sale v{v}, una versión buena: {cause}",
    "flaky_start": "sale v{v}, una versión buena; mientras tanto {cause}",
    "bad_start": "sale v{v}: {cause}",
    "release_end": "se cierra la ventana del despliegue de v{v}",
    "ev_step": "v{v} recibe el {w:.0%} del tráfico",
    "ev_full": "v{v} está activa en todas partes",
    "ev_full_bad": "v{v} está activa en todas partes, y es mala: le llega a cada usuario",
    "ev_caught": "v{v} revertida desde el {w:.0%}: detectada en el canario",
    "ev_false": "v{v} revertida desde el {w:.0%}, pero era buena: una falsa alarma",
    "ev_cancel": "v{v} aún en el {w:.0%} al cerrarse la ventana: anulada",
    "ev_manual": "alguien de guardia revierte v{v} a mano",
    "never": "nunca",
    # el panel
    "tile_hurt": "Daño",
    "tile_errors": "Errores",
    "toplist": "Enrutador",
    "toplist_sub": "peticiones/s, último 1 s",
    "bar_live": "v{v} base",
    "bar_new": "v{v} nueva",
    "bar_none": "nueva –",
    "bar_hurt": "dañadas",
    "head_bad_live": "v{v} es mala y le llega a todos",
    "head_canary": "v{v} al {w:.0%}: midiendo",
    "head_compare": "errores {be:.1%}→{ce:.1%} · lentas {bs:.1%}→{cs:.1%}",
    "head_rolled_back": "v{v} revertida; vuelve v{live}",
    "head_errors": "{e:.1%} errores: una dependencia falla",
    "head_live": "v{v} al 100%; sin despliegues en curso",
    # errores en tu código
    "bad_weight": "decide() devolvió {value}: debe ser un float de 0.0 a 1.0, la parte de la versión nueva",
}

LESSON = Lesson(
    title="Despliegues canario",
    one_liner="Da una versión nueva a unos pocos usuarios primero, compárala con la vieja en los mismos segundos, "
              "y amplíala por etapas solo mientras no sea peor.",
    learn=(
        "La mayoría de los incidentes empiezan con un cambio: un despliegue, un cambio de configuración, un "
        "interruptor. Las pruebas detectan mucho, pero no lo que solo se ve en producción: datos reales, "
        "tráfico real, dependencias reales. Dar una versión a todos los usuarios a la vez convierte cada "
        "versión mala en una caída para todos.",
        "Un despliegue canario manda una parte pequeña del tráfico (1-5%) a la versión nueva y la vigila. Unas "
        "caídas en bucle se ven en segundos, en pocos usuarios, y el despliegue se revierte solo. Eso ya es un "
        "gran paso: el radio del daño es la parte del canario.",
        "Las reglas fijas juzgan mal. Una regresión de latencia no tiene errores, así que un límite de errores "
        "la deja pasar. Un número fijo no distingue una versión mala de un mal momento: cuando la base de "
        "datos conmuta, las dos versiones fallan más y la regla culpa a la nueva. Ponlo bajo y el ruido "
        "revierte versiones buenas; ponlo alto y las regresiones sutiles pasan por debajo.",
        "Compara el canario con una base: la versión vieja, que atiende el resto del tráfico en los mismos "
        "segundos. Una prueba z de dos proporciones dice si la parte de errores (o de lentas) del canario es "
        "de verdad mayor que la de la base o solo ruido. Espera a tener muestras suficientes (un mínimo) "
        "antes de decidir, y pon el listón alto: pruebas muchas métricas, muchas veces.",
        "Mide cada etapa por separado, en total y por ruta o segmento: un fallo que rompe el 5% del "
        "tráfico se diluye en el total. Sube por etapas (5% → 25% → 50% → 100%), cada una el tiempo "
        "suficiente, y revierte de forma automática: las versiones malas nunca llegan a todos, y las buenas "
        "salen en más o menos un minuto.",
    ),
    watch_for=(
        "Todo a la vez: la primera versión es lenta para todos; los puntos se vuelven naranjas y el p99 salta durante dos minutos.",
        "Canario fijo: un hilo morado va a una instancia; las caídas en bucle se revierten en segundos, pero la versión lenta se activa, y una dependencia inestable revierte una buena.",
        "Canario por etapas: la parte morada sube 5% → 25% → 50% → 100% con las versiones buenas; las malas se revierten en las primeras etapas.",
    ),
    build=(
        ("Argo Rollouts: un canario por etapas con análisis",
         "strategy:\n"
         "  canary:\n"
         "    analysis:\n"
         "      templates: [{templateName: error-rate-vs-baseline}]\n"
         "    steps:\n"
         "    - setWeight: 5\n"
         "    - pause: {duration: 5m}\n"
         "    - setWeight: 25\n"
         "    - pause: {duration: 10m}\n"
         "    - setWeight: 50\n"
         "    - pause: {duration: 10m}"),
        ("PromQL: la proporción de errores del canario sobre la de la base",
         "  sum(rate(http_requests_total{track=\"canary\",code=~\"5..\"}[5m]))\n"
         "/ sum(rate(http_requests_total{track=\"canary\"}[5m]))\n"
         "/ ( sum(rate(http_requests_total{track=\"baseline\",code=~\"5..\"}[5m]))\n"
         "  / sum(rate(http_requests_total{track=\"baseline\"}[5m])) )"),
        ("Python: el juez de este laboratorio",
         "def worse(canary, baseline):\n"
         "    for c, b in ((canary.errors, baseline.errors), (canary.slow, baseline.slow)):\n"
         "        if c >= MIN_BAD and z_score(c, canary.requests, b, baseline.requests) > Z_LIMIT:\n"
         "            return True\n"
         "    return False"),
    ),
    checklist=(
        "Nunca des una versión a todos a la vez: empieza con un canario pequeño (1-5%) y una vuelta atrás automática.",
        "Compara el canario con una base que corre la versión vieja a la vez, no con un número fijo.",
        "Juzga errores Y latencia (y saturación): una versión lenta es una versión mala.",
        "Espera un mínimo de peticiones antes de decidir; pon el listón alto si pruebas muchas métricas a menudo.",
        "Mira también por ruta o segmento de clientes: un fallo en uno pequeño se diluye en el total.",
        "Sube por etapas, cada una con su tiempo; acota el tiempo total, para que las buenas salgan pronto.",
    ),
    refs=(
        Ref("Google SRE Workbook: Canarying Releases",
            "https://sre.google/workbook/canarying-releases/",
            "Canario frente a control, qué métricas elegir y por qué importan el tamaño y la duración (en inglés)."),
        Ref("Introducing Kayenta: automated canary analysis (Google y Netflix)",
            "https://cloud.google.com/blog/products/gcp/introducing-kayenta-an-open-automated-canary-analysis-tool-from-google-and-netflix",
            "Un grupo base junto al canario, y un juez estadístico (en inglés)."),
        Ref("Spinnaker: How canary judgment works",
            "https://spinnaker.io/docs/guides/user/canary/judge/",
            "Comparar canario y base métrica a métrica, y puntuar (en inglés)."),
        Ref("Argo Rollouts: Canary deployment strategy",
            "https://argo-rollouts.readthedocs.io/en/stable/features/canary/",
            "Pasos setWeight y pause, con análisis y cancelación automática (en inglés)."),
        Ref("Martin Fowler: CanaryRelease",
            "https://martinfowler.com/bliki/CanaryRelease.html",
            "La idea, en una página (en inglés)."),
        Ref("Wikipedia: Two-proportion Z-test",
            "https://en.wikipedia.org/wiki/Two-proportion_Z-test",
            "La prueba detrás de z_score, con sus supuestos (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/canary_releases/es/main.py y mira cómo se revierten en segundos las caídas en bucle, y cómo se activa la versión lenta.",
        "Haz la etapa 2 y mira cómo las buenas suben 5% → 25% → 50% → 100% mientras las malas se revierten en el canario.",
        "Pon Z_LIMIT a 3 y cuenta las buenas revertidas; quita la comprobación por ruta y mira el fallo en /pay.",
    ),
)

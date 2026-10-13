"""Laboratorio retry_storm, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Tormenta de reintentos"
SUMMARY = "El servicio se cae al azar. Reintenta las llamadas fallidas sin multiplicar la carga."
PARAMS = {"rate": "peticiones de usuarios por segundo"}

INCIDENT = IncidentText("Caída", "la caída", "la próxima caída")
VERBS = {"down": "CAÍDA", "up": "VUELVE"}
CAUSES = {
    "bad_deploy": "un despliegue malo, cada llamada recibe un 503",
    "node_crashed": "el nodo se cayó, conexiones rechazadas",
    "expired_cert": "un certificado TLS caducado, falla cada handshake",
    "config_push": "un cambio de configuración rompió el enrutamiento",
    "pool_exhausted": "su pool de conexiones a la base de datos se agotó",
    "replica_died": "murió una réplica de la base de datos",
    "out_of_memory": "uno de tres nodos se quedó sin memoria",
    "noisy_neighbour": "un vecino ruidoso acapara la CPU",
    "slow_dependency": "una dependencia lenta da timeouts",
    "bad_canary": "un despliegue canario con un bug",
}

STAGES = [
    StageText("Sin reintentos",
              "Reto: el servicio se cae al azar y los usuarios fallan. Reintenta las llamadas fallidas.",
              "Etapa 1: reintenta las llamadas fallidas en Client"),
    StageText("Reintentos",
              "Reto: los reintentos vuelven al instante y machacan el servicio. Espera más cada vez.",
              "Etapa 2: espera backoff_delay(attempt) entre reintentos (exponencial)"),
    StageText("Reintentos + backoff",
              "Reto: todos esperan lo mismo, así que los reintentos llegan en oleadas. Añade jitter.",
              "Etapa 3: añade jitter completo a backoff_delay"),
    StageText("Reintentos + backoff + jitter",
              "Reto: el jitter reparte los reintentos, pero la carga sigue x4. Ponles un tope.",
              "Etapa 4: gasta un RetryBudget en cada reintento"),
    StageText("Reintentos + backoff + jitter + presupuesto",
              "Resuelto: los reintentos esperan con jitter y gastan un presupuesto; la carga no sube.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "Client debe devolver algo"),
    "retries": GoalText("Reintentos ≥ 3%", "reintenta ServiceError"),
    "backoff": GoalText("Backoff ≥ 1.5x", "usa backoff_delay(attempt)"),
    "jitter": GoalText("Jitter ≥ 25%", "añade jitter a backoff_delay"),
    "load": GoalText("Carga < 1.5x", "gasta tokens de RetryBudget"),
    "served": GoalText("Servidas ≥ 90%", "reintenta cuando vuelva"),
}

LEGEND = {"idle": "en reposo", "first_try": "primer intento", "retries": "reintento 1,2,3", "failed": "fallida",
          "served": "servida", "limit": "límite", "incident": "incidente"}

STRINGS = {
    # incidentes
    "partial_outage": "Caída parcial",
    "down": "está caído: {cause}",
    "back_up": "vuelve a funcionar",
    "failing": "falla el {share:.0%} de las llamadas: {cause}",
    "healthy_again": "vuelve a estar sano",
    "warn_load": "carga {load:.1f}x lo que piden los usuarios",
    # valores de los objetivos
    "avg": "media {value:.1f}x",
    "few": "pocos",
    # el panel
    "tile_load": "Carga",
    "tile_retries": "Reint.",
    "tile_served": "Servido",
    "bar_ask": "Piden",
    "bar_get": "Recibimos",
    "limit": "límite {limit:.0f}/s",
    "head_down": "Caído: recibimos {load:.1f}x lo que piden",
    "head_failing": "Falla {share:.0%}: recibimos {load:.1f}x lo que piden",
    "head_recovered": "Recuperado {seconds:.0f} s después de la caída",
    "head_draining": "Ya funciona; aún se vacían los reintentos",
    "head_load": "Carga: {load:.1f}x lo que piden",
    "note_dots": "Los puntos son una muestra de llamadas, más lentas (estético).",
    # errores en tu código
    "stuck": "una petición lleva más de {seconds:.0f} s: ¿Client.call reintenta sin fin?",
}

LESSON = Lesson(
    title="Tormenta de reintentos",
    one_liner="El servicio se cae unos segundos. Clientes que reintentan al momento convierten 100 llamadas/s en ~400.",
    learn=(
        "Cuando un servicio falla, cada cliente ve errores y vuelve a intentarlo enseguida. Con 3 "
        "reintentos rápidos, una petición se convierte en hasta 4 llamadas, así que el servicio recibe "
        "~4 veces su tráfico normal justo cuando está más débil. Entre capas se multiplica: 3 reintentos "
        "en cada una de 3 capas pueden ser 64 intentos abajo del todo.",
        "Backoff con jitter: espera más tras cada fallo, y elige la espera al azar para que los clientes "
        "no reintenten a la vez. El jitter completo espera uniform(0, min(cap, base * 2**attempt)).",
        "Un presupuesto de reintentos: el backoff reparte los reintentos pero no los limita. Un "
        "presupuesto sí. Cada petición suma una fracción de token (digamos 0.1), cada reintento gasta "
        "uno, y cuando el cubo se vacía fallas rápido. El tráfico de reintentos se queda cerca de un 10% "
        "extra, dure lo que dure la caída.",
        "Elige una sola capa que reintente (biblioteca cliente, malla o gateway) y que las demás fallen rápido.",
    ),
    watch_for=(
        "Sin reintentos: durante la caída la tarjeta Servidas baja a 0% y los usuarios fallan (rojo).",
        "Reintentos: los puntos naranjas son reintentos que vuelven al instante. 'Recibimos' es ~4x 'Piden'.",
        "Reintentos + backoff: las esperas se duplican en cada ronda, pero todos esperan lo mismo: oleadas.",
        "Reintentos + backoff + jitter: los reintentos se reparten, pero la carga sigue ~4x.",
        "Con presupuesto: pasan algunos reintentos y luego el presupuesto se agota.",
        "El presupuesto no recupera antes el servicio; evita que lo entierres mientras está caído.",
    ),
    build=(
        ("En Python (stamina envuelve tenacity con valores seguros)",
         "import httpx, stamina\n\n"
         "@stamina.retry(on=httpx.TransportError, attempts=3)\n"
         "async def call_b(client: httpx.AsyncClient) -> dict:\n"
         "    r = await client.get(\"http://b/work\", timeout=1.0)   # timeout por intento\n"
         "    r.raise_for_status()\n"
         "    return r.json()"),
        ("Configuración de servicio gRPC: el retry throttling es el presupuesto de este laboratorio",
         "\"retryThrottling\": {\"maxTokens\": 10, \"tokenRatio\": 0.1}"),
        ("Clúster de Envoy: un presupuesto de reintentos",
         "circuit_breakers:\n"
         "  thresholds:\n"
         "  - retry_budget:\n"
         "      budget_percent: {value: 10.0}\n"
         "      min_retry_concurrency: 3"),
    ),
    checklist=(
        "Solo una capa reintenta. Enuméralas: SDK, biblioteca cliente, malla, gateway.",
        "Reintenta solo errores transitorios (fallos de conexión, 503, 429) en peticiones que se pueden repetir.",
        "Un timeout por intento, y un plazo total que se pasa a la siguiente llamada.",
        "Backoff exponencial con jitter completo y un tope. Respeta Retry-After.",
        "Un presupuesto o limitador de reintentos, de un 10% más o menos.",
        "Métricas: reintentos por primer intento, intentos por petición, presupuesto agotado. Alerta sobre el ratio.",
        "Pruébalo: para una dependencia en staging y mira las llamadas/s. Debería parecerse a la última etapa.",
    ),
    refs=(
        Ref("AWS Builders' Library: Timeouts, retries and backoff with jitter",
            "https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/",
            "Cuándo reintentar, cuándo no, y por qué importa el jitter (en inglés)."),
        Ref("AWS Architecture Blog: Exponential Backoff And Jitter",
            "https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/",
            "Simulaciones de jitter completo, igual y decorrelado; la fórmula usada aquí (en inglés)."),
        Ref("Google SRE book: Addressing Cascading Failures",
            "https://sre.google/sre-book/addressing-cascading-failures/",
            "Backoff aleatorio, límites de reintentos y cómo se multiplican entre capas (en inglés)."),
        Ref("gRPC: Retry",
            "https://grpc.io/docs/guides/retry/",
            "Política de reintentos y retry throttling (maxTokens, tokenRatio) (en inglés)."),
        Ref("Envoy: circuit breakers and retry budgets",
            "https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/circuit_breaking",
            "El presupuesto de Envoy limita los reintentos a una parte de las peticiones activas (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/retry_storm/es/main.py, guarda y mira cómo sube la carga.",
        "Haz la etapa 2 y mira cómo el objetivo Backoff se pone verde mientras la carga sigue alta.",
        "Haz la etapa 3 y mira cómo el objetivo Jitter se pone verde.",
        "Haz la etapa 4 y mira cómo desaparece el naranja mientras el servicio está caído.",
        "Ejecuta `LABS_LANG=es uv run pytest labs/retry_storm` y mira cómo las x se vuelven X.",
    ),
)

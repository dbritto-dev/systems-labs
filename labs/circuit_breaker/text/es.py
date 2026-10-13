"""Laboratorio circuit_breaker, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Circuit breaker"
SUMMARY = "Una dependencia lenta acapara todos los workers. Añade timeouts, un bulkhead y un circuit breaker."
PARAMS = {"rate": "peticiones de usuarios por segundo", "workers": "workers de nuestro servicio"}

INCIDENT = IncidentText("Lentitud", "la lentitud", "la próxima lentitud")
VERBS = {"slow": "LENTO", "fast": "RÁPIDO"}
CAUSES = {
    "ledger_lock": "un bloqueo en la tabla del libro contable",
    "provider_brownout": "una degradación de red hacia el proveedor de pagos",
    "payments_gc": "una tormenta de GC en el servicio de pagos",
    "rate_limited": "el proveedor de pagos nos está limitando",
    "recs_gc": "una tormenta de GC en el servicio de recomendaciones",
    "cold_cache": "una caché de modelos en frío tras un despliegue",
    "slow_features": "un feature store lento",
    "noisy_neighbour": "un vecino ruidoso en su base de datos",
}

STAGES = [
    StageText("Sin protección",
              "Reto: una dependencia lenta retiene todos los workers y todo falla. Añade timeouts.",
              "Etapa 1: abandona una llamada tras TIMEOUT"),
    StageText("Timeouts",
              "Reto: las llamadas lentas aún retienen workers un segundo. Aísla cada dependencia.",
              "Etapa 2: un Bulkhead por dependencia"),
    StageText("Timeouts + bulkhead",
              "Reto: lo sano está a salvo, pero se espera 1 s a la dependencia lenta. Falla rápido.",
              "Etapa 3: un CircuitBreaker por dependencia"),
    StageText("Timeouts + bulkhead + breaker",
              "Resuelto: la dependencia lenta queda aislada y falla rápido; el resto sigue funcionando.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "Client debe devolver algo"),
    "calls": GoalText("Llamadas ≤ 1.2s", "corta tras TIMEOUT"),
    "healthy": GoalText("Sana ≥ 99%", "un Bulkhead por dependencia"),
    "fast": GoalText("Falla rápido <50ms", "un CircuitBreaker por dep."),
    "back": GoalText("Vuelve ≥ 95%", "cierra el breaker otra vez"),
}

LEGEND = {"idle": "en reposo", "fast_call": "llamada rápida", "waits_worker": "espera un worker",
          "slow_call": "llamada lenta", "refused": "rechazada", "failed": "fallida", "served": "servida",
          "workers": "workers", "incident": "incidente"}

STRINGS = {
    # las dependencias (barras: 10 letras como máximo)
    "dep_payments": "Pagos",
    "dep_recs": "Recomend.",
    # incidentes
    "title": "{dep} lento",
    "slow": "{dep} va lento, {seconds:.0f} s por llamada: {cause}",
    "fast_again": "{dep} vuelve a ir rápido",
    "warn_busy": "los {workers} workers están ocupados",
    # el panel
    "tile_healthy": "Sana",
    "tile_fails": "Falla",
    "tile_workers": "Uso",
    "target_busy": "workers",
    "answers": "Respuestas",
    "head_both_fail": "{dep} lento y {healthy} también falla",
    "head_contained": "{dep} lento; {healthy} va bien",
    "head_still_open": "{dep} volvió; el breaker sigue abierto",
    "head_back": "{dep} volvió",
    "head_calm": "Las dos dependencias responden rápido",
    "chart_limit": "{workers} workers",
    "note_chart": "La gráfica: workers ocupados por segundo.",
    # errores en tu código
    "stuck": "una petición lleva más de {seconds:.0f} s: ¿Client.call espera algo que nunca termina?",
}

LESSON = Lesson(
    title="Circuit breaker",
    one_liner="Una sola dependencia lenta puede retener todos tus workers, y entonces todo falla.",
    learn=(
        "Una dependencia lenta es peor que una caída. Una caída falla rápido; una lenta retiene un "
        "worker (un hilo, una conexión, un hueco) por cada llamada. A 40 llamadas/s y 8 s por llamada "
        "quiere 320 workers. Con 24, el pool se llena en un segundo, y las peticiones que ni siquiera "
        "tocan la dependencia lenta hacen cola detrás y fallan: un fallo en cascada.",
        "Los timeouts limitan cuánto tiempo puede retener un worker una llamada. Son necesarios, pero "
        "no bastan: 40 llamadas/s con un timeout de 1 s siguen queriendo 40 workers.",
        "Un bulkhead limita cuántos workers puede retener cada dependencia (como los mamparos estancos "
        "del casco de un barco). La dependencia lenta hunde su propio compartimento, no todo el servicio.",
        "Un circuit breaker detecta los fallos y deja de llamar durante un rato: las llamadas fallan "
        "al instante en vez de esperar al timeout. Tras una pausa deja pasar una prueba (half-open), y "
        "se vuelve a cerrar cuando la dependencia responde.",
    ),
    watch_for=(
        "Sin protección: la tarjeta de workers llega a 24/24 y la dependencia sana también falla.",
        "Timeouts: las llamadas se abandonan tras 1 s, pero el pool se sigue llenando mientras va lenta.",
        "Timeouts + bulkhead: la dependencia sana va bien; quien usa la lenta espera 1 s para fallar.",
        "Timeouts + bulkhead + breaker: la puerta se cierra, las llamadas fallan en menos de 1 ms, y se reabre después.",
    ),
    build=(
        ("Python: un timeout en cada llamada",
         "async with asyncio.timeout(1.0):\n"
         "    return await client.get(url)"),
        ("resilience4j (Java): un breaker y un bulkhead alrededor de una llamada",
         "CircuitBreaker cb = CircuitBreaker.ofDefaults(\"recs\");\n"
         "Bulkhead bh = Bulkhead.of(\"recs\", BulkheadConfig.custom().maxConcurrentCalls(10).build());\n"
         "Supplier<Recs> call = Decorators.ofSupplier(recs::fetch)\n"
         "    .withCircuitBreaker(cb).withBulkhead(bh).decorate();"),
        ("Envoy: detección de outliers y límites de conexiones por clúster",
         "circuit_breakers:\n"
         "  thresholds: [{max_connections: 100, max_pending_requests: 50}]\n"
         "outlier_detection:\n"
         "  consecutive_5xx: 5\n"
         "  base_ejection_time: 30s"),
    ),
    checklist=(
        "Cada llamada saliente tiene un timeout, más corto que el plazo de quien llama.",
        "Cada dependencia tiene su propio pool o límite de concurrencia (un bulkhead).",
        "Un breaker por dependencia (o por host), con métricas de sus cambios de estado.",
        "Un plan B cuando el breaker está abierto: una respuesta en caché, un valor por defecto o un error claro.",
        "Alerta cuando se abre un breaker, y pruébalo: ralentiza una dependencia en staging.",
    ),
    refs=(
        Ref("Martin Fowler: CircuitBreaker",
            "https://martinfowler.com/bliki/CircuitBreaker.html",
            "El patrón, sus tres estados y una implementación pequeña (en inglés)."),
        Ref("Azure Architecture Center: Circuit Breaker pattern",
            "https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker",
            "Cuándo usarlo, el estado half-open y qué vigilar (en inglés)."),
        Ref("Azure Architecture Center: Bulkhead pattern",
            "https://learn.microsoft.com/en-us/azure/architecture/patterns/bulkhead",
            "Aislar recursos por consumidor o dependencia para que un fallo quede contenido (en inglés)."),
        Ref("resilience4j: CircuitBreaker",
            "https://resilience4j.readme.io/docs/circuitbreaker",
            "Un breaker de producción: ventanas deslizantes, tasa de fallos y umbrales de llamadas lentas (en inglés)."),
        Ref("Google SRE book: Addressing Cascading Failures",
            "https://sre.google/sre-book/addressing-cascading-failures/",
            "Cómo se propaga el agotamiento de recursos y las defensas que lo frenan (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/circuit_breaker/es/main.py y mira cómo las llamadas lentas se cortan a 1 s.",
        "Haz la etapa 2 y mira cómo la dependencia sana conserva sus workers.",
        "Haz la etapa 3 y mira cómo la puerta se cierra mientras va lenta y se abre otra vez después.",
        "Prueba --set workers=60: ¿cuánta lentitud aguantan solo los timeouts?",
    ),
)

"""Laboratorio hedged_requests, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Peticiones de respaldo"
SUMMARY = "Unas pocas respuestas lentas marcan el p99. Manda una copia si la primera tarda, con un presupuesto."
PARAMS = {"rate": "lecturas de usuarios por segundo"}

INCIDENT = IncidentText("Lentitud", "la lentitud", "la próxima lentitud")
VERBS = {"slow": "LENTA", "fast": "RÁPIDA"}
CAUSES = {
    "compaction": "una compactación que reescribe sus archivos",
    "noisy_neighbour": "un vecino ruidoso en su máquina",
    "degraded_volume": "un volumen de disco degradado",
    "backup_snapshot": "una instantánea de copia de seguridad que lee su disco",
    "index_rebuild": "una reconstrucción de índice",
    "hot_key": "una clave caliente que leen todos los usuarios",
    "cold_caches": "cachés en frío tras un despliegue",
    "slow_storage": "un almacenamiento compartido lento",
    "zone_congestion": "una red congestionada entre zonas",
}

STAGES = [
    StageText("Una llamada",
              "Reto: 1 respuesta de cada 50 es lenta y marca el p99. Manda una copia si tarda.",
              "Etapa 1: copia tras HEDGE_AFTER en Client.read"),
    StageText("Copia",
              "Reto: el p99 bajó, pero una réplica lenta cuesta una copia por lectura. Limita y cancela.",
              "Etapa 2: un HedgeBudget, y cancela la perdedora"),
    StageText("Copia + presupuesto + cancelar",
              "Resuelto: las copias tapan las respuestas lentas, con poca carga extra y nada perdido.",
              "Todas las etapas hechas"),
]

GOALS = {
    "tail": GoalText("p99 ≤ 50ms", "copia tras HEDGE_AFTER"),
    "extra": GoalText("Extra ≤ 10%", "usa un HedgeBudget"),
    "waste": GoalText("Perdido ≤ 5%", "cancela la llamada perdedora"),
    "served": GoalText("Servidas ≥ 99%", "devuelve la primera"),
    "back": GoalText("Vuelve p99 ≤ 50ms", "rellena el presupuesto"),
}

LEGEND = {"idle": "en reposo", "first_call": "primera llamada", "slow_reply": "respuesta lenta", "copy": "copia",
          "wasted": "perdedora aún en curso", "failed": "fallida", "served": "servida", "limit": "10% extra",
          "incident": "incidente"}

STRINGS = {
    "note_dots": "Los puntos son una muestra, más lentos (estético).",
    "note_chart": "La gráfica: copias enviadas por segundo.",
    # el dibujo de clúster: la topología bajo la cuadrícula
    "topology": "servicio → {n} réplicas",
    # el nombre de una réplica (barras: 10 letras como máximo)
    "replica": "Réplica {n}",
    # incidentes
    "title_one": "{replica} lenta",
    "title_all": "Todas lentas",
    "slow_one": "{replica} va lenta, {ms} por respuesta: {cause}",
    "fast_one": "{replica} vuelve a ir rápida",
    "slow_all": "todas las réplicas van lentas, {ms} por respuesta: {cause}",
    "fast_all": "todas las réplicas vuelven a ir rápidas",
    "warn_extra": "las copias añaden un {extra:.0%} de carga",
    # el panel
    "tile_extra": "Extra",
    "tile_waste": "Perdido",
    "head_all_storm": "Todas lentas: copias suman +{extra:.0%}",
    "head_all_capped": "Todas lentas: copias frenadas",
    "head_one_hidden": "{replica} lenta: copias +{extra:.0%}",
    "head_one_capped": "{replica} lenta: copias limitadas",
    "head_one_waits": "{replica} lenta: la esperan",
    "head_back": "Rápida otra vez; quedan lentas",
    "head_tail": "Respuestas lentas: p99 {p99}",
    "head_hedged": "Copias tapan lo lento: p99 {p99}",
    "head_calm": "Las respuestas son rápidas",
    "chart_limit": "{extra:.0%} extra",
    # errores en tu código
    "stuck": "una lectura lleva más de {seconds:.0f} s: ¿Client.read espera algo que nunca termina?",
}

LESSON = Lesson(
    title="Peticiones de respaldo",
    one_liner="Unas pocas respuestas lentas marcan el p99; una segunda copia, enviada tarde y con presupuesto, las tapa.",
    learn=(
        "Casi todas las respuestas tardan ~10 ms, pero 1 de cada 50 tarda 100-400 ms: una pausa de "
        "GC, un fallo de caché, un disco lento. Es raro para una llamada y habitual para los "
        "usuarios: el p99 ES esa respuesta lenta. A gran escala una página consulta muchos "
        "servidores, y casi todas se topan con una (Dean y Barroso, \"The Tail at Scale\").",
        "Una petición de respaldo espera un poco (más o menos el p95 de una respuesta) y, si aún no "
        "hay respuesta, manda la misma lectura a otra réplica y se queda con la que conteste antes. "
        "Dos respuestas lentas seguidas son muy raras (1 de cada 2.500), así que el p99 baja a "
        "~30 ms. Solo el ~2% lento recibe copia, así que cuesta ~2% más de carga.",
        "Sin límite, se vuelve en tu contra justo cuando algo va mal. Si una réplica va lenta, cada "
        "lectura que le llega recibe copia: +33% de carga. Si van lentas todas, todas la reciben: "
        "el doble de carga sobre una flota que ya sufre. Un presupuesto de copias (como el de "
        "reintentos) permite copias para ~5% de las lecturas como mucho; pasado eso, se espera.",
        "Cancela la perdedora. Cuando una copia ya respondió, la otra es trabajo que nadie necesita: "
        "una réplica lenta la retiene su medio segundo entero, en un disco o una cola ya saturados.",
        "Las copias tapan lentitudes breves y al azar. Una réplica que sigue lenta es otro problema: "
        "sácala de la rotación un tiempo (el artículo lo llama periodo de prueba; Envoy, detección "
        "de valores atípicos).",
    ),
    watch_for=(
        "Una llamada: la tarjeta p99 está en rojo sin que nada falle: unas pocas respuestas lentas la marcan.",
        "Copia: copias naranjas vuelan a otra réplica; p99 ~30 ms, pero Extra es +35% si una réplica va lenta.",
        "Copia: perdedoras en naranja intenso se acumulan junto a la réplica lenta, aún en curso: la tarjeta Perdido.",
        "Copia + presupuesto + cancelar: las copias se quedan en pocos %; en carriles (v) la puerta se cierra "
        "mientras el presupuesto está agotado.",
    ),
    build=(
        ("Go: una lectura con copia, cancelando la perdedora",
         "res := make(chan Result, 2) // sitio para las dos: la perdedora nunca se bloquea\n"
         "ctx, cancel := context.WithCancel(ctx)\n"
         "defer cancel() // la llamada perdedora se detiene\n"
         "go func() { res <- replicaA.Get(ctx, key) }()\n"
         "select {\n"
         "case r := <-res: return r\n"
         "case <-time.After(20 * time.Millisecond): // ~p95: manda una copia\n"
         "    go func() { res <- replicaB.Get(ctx, key) }()\n"
         "}\n"
         "return <-res"),
        ("Configuración de servicio de gRPC: una política de copias con limitación",
         "\"hedgingPolicy\": {\"maxAttempts\": 2, \"hedgingDelay\": \"0.02s\"},\n"
         "\"retryThrottling\": {\"maxTokens\": 10, \"tokenRatio\": 0.1}"),
        ("Envoy: copia cuando vence el timeout de cada intento",
         "hedge_policy: {hedge_on_per_try_timeout: true}\n"
         "retry_policy: {per_try_timeout: 0.02s, num_retries: 1}"),
    ),
    checklist=(
        "Copia solo lecturas idempotentes (o escrituras con una clave de idempotencia).",
        "Fija la espera antes de la copia con la latencia medida (más o menos el p95), no a ojo.",
        "Limita las copias con un presupuesto o un cubo de tokens compartido por todo el cliente.",
        "Cancela la llamada perdedora, y haz que el servidor deje de trabajar cuando se cancela.",
        "Mide las copias enviadas por petición; avisa cuando suban.",
        "Combínalo con la detección de valores atípicos, para sacar una réplica que sigue lenta.",
    ),
    refs=(
        Ref("Dean y Barroso: The Tail at Scale (CACM 2013)",
            "https://research.google/pubs/the-tail-at-scale/",
            "Por qué las respuestas lentas raras dominan a gran escala, y las peticiones de respaldo y atadas."),
        Ref("The Tail at Scale (PDF)",
            "https://www.barroso.org/publications/TheTailAtScale.pdf",
            "El artículo: una copia tras 10 ms bajó un p99.9 de 1.800 ms a 74 ms, con un 2% más de peticiones."),
        Ref("gRPC: Request Hedging",
            "https://grpc.io/docs/guides/request-hedging/",
            "hedgingDelay, maxAttempts y la limitación con tokens."),
        Ref("gRFC A6: reintentos y copias en el cliente de gRPC",
            "https://github.com/grpc/proposal/blob/master/A6-client-retries.md",
            "El diseño: la política de copias y el cubo de tokens que la limita."),
        Ref("Marc Brooker: Tail Latency Might Matter More Than You Think",
            "https://brooker.co.za/blog/2021/04/19/latency.html",
            "Cómo consultar a muchos servidores convierte una respuesta lenta rara en una petición lenta habitual."),
        Ref("Finagle: MethodBuilder (peticiones de respaldo)",
            "https://twitter.github.io/finagle/guide/MethodBuilder.html",
            "Peticiones de respaldo en producción: se envían en un percentil, con un tope de tráfico."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/hedged_requests/es/main.py y mira cómo la tarjeta p99 se pone en verde.",
        "Espera a una réplica lenta: mira cómo Extra pasa del 30% y las perdedoras se acumulan junto a ella.",
        "Haz la etapa 2 y mira cómo las copias se quedan en pocos % y las perdedoras desaparecen.",
        "Prueba --set rate=300: ¿el presupuesto sigue limitando las copias?",
    ),
)

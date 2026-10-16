"""Laboratorio deadline_propagation, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Propagación del plazo"
SUMMARY = "Cuatro servicios en cadena siguen trabajando cuando el usuario ya se fue. Pasa el plazo y salta lo tardío."
PARAMS = {"rate": "peticiones de usuarios por segundo", "connections": "conexiones de la base de datos (su pool)"}

INCIDENT = IncidentText("Lentitud", "la lentitud", "la próxima lentitud")
VERBS = {"slow": "LENTA", "fast": "RÁPIDA"}
CAUSES = {
    "slow_query": "un plan de consulta lento tras un despliegue",
    "lock_contention": "contención de bloqueos en la tabla de pedidos",
    "degraded_replica": "lecturas desviadas a una réplica degradada",
    "gc_storm": "una tormenta de GC en los nodos de la base de datos",
    "vacuum": "una tarea de mantenimiento que satura los discos",
    "cold_cache": "una caché de búferes en frío tras un failover",
}

STAGES = [
    StageText("Timeouts por salto",
              "Reto: cada salto espera sus propios 2 s y sigue esperando cuando el usuario ya se fue.",
              "Etapa 1: pasa el plazo hacia abajo (next_deadline)"),
    StageText("Plazo propagado",
              "Reto: los saltos se rinden a tiempo, pero la BD aún consulta para quien ya se fue.",
              "Etapa 2: salta el trabajo si expired()"),
    StageText("Plazo + saltar lo tardío",
              "Resuelto: la cadena se rinde con el usuario y nunca trabaja para quien ya se fue.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "handle debe devolver \"ok\""),
    "waste": GoalText("Desperdicio ≤ 5%", "salta el trabajo vencido"),
    "served": GoalText("Servidas ≥80% máx", "falla rápido si ya venció"),
    "overrun": GoalText("Exceso p99 <10ms", "pasa el plazo hacia abajo"),
}

LEGEND = {"idle": "en reposo", "waiting": "esperando", "waiting_long": "esperando > 1 s", "served": "servida",
          "failed": "fallida", "abandoned": "se fue, aún en proceso", "incident": "incidente"}

STRINGS = {
    "note_dots": "Los puntos son una muestra, más lentos (decorativo).",
    "note_chart": "La gráfica: consultas a la BD por segundo; en rojo, las de usuarios que ya se fueron.",
    # los servicios (barras: 10 letras como máximo)
    "hop_gateway": "Pasarela",
    "hop_api": "API",
    "hop_orders": "Pedidos",
    "hop_db": "BD",
    # el estado bajo el dibujo
    "state_dead": "{dead}/{n} para nadie",
    # incidentes
    "title": "BD lenta",
    "slow": "la BD va lenta, {ms:.0f} ms por consulta: {cause}",
    "fast_again": "la BD vuelve a ir rápida",
    "warn_waste": "la mayoría de las consultas son de usuarios que ya se fueron",
    # el panel
    "tile_waste": "Desperd.",
    "tile_served": "Servidas",
    "tile_overrun": "Exceso",
    "at_hops": "Peticiones",
    "at_hops_sub": "en cada servicio ahora",
    "head_waste": "La BD atiende a quien ya se fue",
    "head_slow": "BD lenta; sin desperdicio",
    "head_backlog": "La BD volvió; vacía lo atrasado",
    "head_back": "La BD vuelve a ir rápida",
    "head_calm": "Todo responde rápido",
    # errores en tu código
    "stuck": "una petición lleva más de {seconds:.0f} s ocupando un worker: ¿handle espera algo que nunca termina?",
}

LESSON = Lesson(
    title="Propagación del plazo",
    one_liner="Que un usuario se rinda no detiene el trabajo: solo lo hace un plazo que baja por la cadena.",
    learn=(
        "Una petición cruza varios servicios: pasarela → api → pedidos → base de datos. El usuario se "
        "rinde a los 2 s, pero nadie se lo dice a los servicios. Si cada salto tiene su propio timeout "
        "de 2 s, contado desde que ÉL llamó, los timeouts no suman lo mismo que el del usuario: un "
        "salto que recibió la petición tarde (tras una cola) sigue esperando mucho después de que el "
        "usuario se fue, ocupando un worker.",
        "Peor aún, el final de la cadena nunca se entera de que nadie espera. Cuando la base de datos "
        "se vuelve lenta, se forma una cola delante de ella, y ejecuta cada consulta de esa cola, "
        "también las de usuarios que se fueron hace segundos. Ese trabajo desperdiciado le quita "
        "capacidad a las peticiones vivas, la cola crece, más usuarios se rinden y la lentitud se "
        "alimenta sola.",
        "Propagación del plazo: el cliente envía un plazo absoluto (cuándo deja de esperar), y cada "
        "salto lo pasa al siguiente restándole un margen, así el siguiente debe terminar un poco antes "
        "que él: su respuesta llega a tiempo, y el trabajo que empiece justo antes de su plazo aún "
        "puede terminar. Cada salto espera solo lo que espera quien lo llamó, y toda la cadena se "
        "rinde a la vez.",
        "Como conoce el plazo, un servicio puede saltarse el trabajo que nadie verá: lo comprueba antes "
        "de la parte cara (una consulta, una llamada al siguiente servicio) y falla rápido si ya pasó. "
        "La cola se vacía al instante, y el tiempo de la base de datos va para los usuarios que siguen "
        "ahí.",
    ),
    watch_for=(
        "Timeouts por salto: el exceso llega a decenas de ms o a segundos; se acumulan anillos rojos.",
        "Plazo propagado: el exceso baja a 0, pero la parte roja de la gráfica (consultas inútiles) sigue.",
        "Plazo + saltar lo tardío: nada rojo en la gráfica, y las servidas se quedan cerca del máximo posible.",
    ),
    build=(
        ("Go: el contexto lleva el plazo a cada llamada, también a la consulta",
         "ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)\n"
         "defer cancel()\n"
         "if ctx.Err() != nil { return ctx.Err() }  // salta el trabajo que nadie espera\n"
         "rows, err := db.QueryContext(ctx, q)    // la base de datos también para en el plazo"),
        ("gRPC (Python): pasa lo que queda, menos un margen",
         "left = context.time_remaining() - 0.05\n"
         "if left <= 0:\n"
         "    context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, \"demasiado tarde\")\n"
         "reply = orders_stub.Get(req, timeout=left)"),
        ("Envoy: el enrutador le dice al servicio de destino cuánto esperará",
         "route:\n"
         "  timeout: 2s\n"
         "# el destino lee x-envoy-expected-rq-timeout-ms y puede rendirse antes"),
    ),
    checklist=(
        "El borde (la pasarela o el cliente) fija un plazo por petición, cercano a lo que esperan los usuarios.",
        "Cada salto pasa el plazo al siguiente (gRPC lo hace por ti), menos un pequeño margen.",
        "Cada llamada saliente y cada consulta usan el tiempo que queda, nunca un timeout fijo propio.",
        "Comprueba el plazo antes del trabajo caro y antes de cada llamada; falla rápido si ya pasó.",
        "Mide el trabajo hecho después del plazo (trabajo desperdiciado): debería ser casi cero.",
    ),
    refs=(
        Ref("gRPC: Deadlines",
            "https://grpc.io/docs/guides/deadlines/",
            "Fijar un plazo en el cliente, comprobarlo en el servidor y propagarlo (en inglés)."),
        Ref("gRPC blog: gRPC and Deadlines",
            "https://grpc.io/blog/deadlines/",
            "Por qué cada llamada necesita un plazo, y cómo deben comprobarlo los servidores (en inglés)."),
        Ref("Google SRE book: Addressing Cascading Failures",
            "https://sre.google/sre-book/addressing-cascading-failures/",
            "Propagación del plazo, plazos vencidos y trabajo para peticiones que nadie espera (en inglés)."),
        Ref("AWS Builders' Library: Using load shedding to avoid overload",
            "https://aws.amazon.com/builders-library/using-load-shedding-to-avoid-overload/",
            "Pistas de timeout de los clientes, y saltarse el trabajo de peticiones ya vencidas (en inglés)."),
        Ref("Go: package context",
            "https://pkg.go.dev/context",
            "Plazos y cancelación que cruzan límites de API y goroutines (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/deadline_propagation/es/main.py y mira cómo el exceso baja a 0.",
        "Haz la etapa 2 y mira cómo desaparecen de la gráfica las consultas en rojo.",
        "Prueba --set connections=6: con capacidad de sobra en la base de datos, ¿importa algo de esto?",
        "Pon MARGIN = 0.0 en tu archivo: ¿por qué bajan las peticiones servidas?",
    ),
)

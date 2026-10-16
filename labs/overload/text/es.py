"""Laboratorio overload, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Sobrecarga y colas"
SUMMARY = "Un pico llena la cola de usuarios que ya se fueron. Descarta carga y el servidor se recupera."
PARAMS = {"rate": "usuarios por segundo (cada uno espera 1 s y reintenta hasta dos veces)"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"spike": "PICO", "calm": "CALMA", "drop": "BAJA", "up": "NORMAL"}
CAUSES = {
    "viral_post": "una publicación se hizo viral",
    "thundering_herd": "una estampida de clientes tras un despliegue",
    "early_batch": "el proceso por lotes de un socio empezó antes de hora",
    "app_retry_storm": "una tormenta de reintentos tras publicar la app móvil",
    "cache_flushed": "se vació una caché que tenía delante",
    "node_lost": "se perdió uno de sus nodos",
    "noisy_neighbour": "un vecino ruidoso acapara la CPU",
    "bad_config": "una mala configuración dejó la mitad de workers",
    "gc_pauses": "pausas del recolector de basura",
}

STAGES = [
    StageText("FIFO sin límite",
              "Reto: tras un pico la cola se llena de usuarios que ya se fueron y no se recupera.",
              "Etapa 1: rechaza en la puerta cuando la cola está llena"),
    StageText("Cola con límite",
              "Reto: la cola tiene límite, pero el servidor sigue trabajando para quien ya se fue.",
              "Etapa 2: salta las peticiones que ya llegan tarde"),
    StageText("Salta lo tardío",
              "Reto: nada se desperdicia, pero cada respuesta llega al límite. Sirve primero lo nuevo.",
              "Etapa 3: lo más nuevo primero mientras la cola es larga"),
    StageText("LIFO adaptativo",
              "Resuelto: la cola tiene límite, nada se desperdicia y lo nuevo se responde rápido.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "responde a tiempo"),
    "queue": GoalText("Cola ≤ 250", "rechaza con la cola llena"),
    "waste": GoalText("Desperd. < 5%", "salta lo que llega tarde"),
    "goodput": GoalText("Goodput ≥ 80%", "no sirvas a quien se fue"),
    "fast": GoalText("Rápido < 300ms", "lo nuevo primero si es larga"),
    "recovered": GoalText("Recupera ≤ 5 s", "descarta carga para volver"),
}

LEGEND = {"idle": "en reposo", "first_try": "primer intento", "retries": "reintento 1.2",
          "wasted": "trabajo para quien se fue", "rejected": "rechazada", "in_time": "a tiempo",
          "max": "máximo", "incident": "incidente"}

STRINGS = {
    # el dibujo de clúster: la topología bajo la cuadrícula
    "topology": "cola → servidor",
    # incidentes
    "capacity_drop": "Baja de capacidad",
    "spike": "Pico",
    "back_to_normal": "vuelve a la normalidad",
    "capacity_down": "baja al {share:.0%} de capacidad: {cause}",
    "traffic_up": "recibe {factor:.1f}x el tráfico: {cause}",
    "warn_queue": "la cola pasó de {limit}",
    "warn_waste": "{share:.0%} del trabajo desperdiciado",
    # valores de los objetivos
    "seconds": "{seconds:.0f} s",
    "over_seconds": ">{seconds:.0f} s",
    # el panel
    "tile_served": "Servido",
    "tile_waste": "Desperd.",
    "tile_reply": "Resp.",
    "bar_arrive": "Llegan",
    "bar_server": "Servidor",
    "bar_rejected": "Rechazos",
    "toplist": "Peticiones",
    "max": "máx {limit:.0f}/s",
    "head_wasted": "{share:.0%} del trabajo es para nadie",
    "head_capacity": "Capacidad bajó a {capacity:.0f}/s; {waiting} esperando",
    "head_rejecting": "Lo que sobra se rechaza en la puerta",
    "head_ok": "Cada respuesta llega a tiempo",
    "stat_gave_up": "se rindieron",
    "stat_rejected": "rechazadas",
    "note_dots": "Puntos: una muestra, más lenta (decorativo).",
    # el dibujo
    "state_wasting": "DERROCHA",
    # errores en tu código
    "stuck": "un usuario lleva esperando más de {seconds:.0f} s",
}

LESSON = Lesson(
    title="Sobrecarga y colas",
    one_liner="Un pico corto puede dejar un servidor ocupado para siempre, trabajando para usuarios que ya se fueron.",
    learn=(
        "Una cola absorbe una ráfaga, pero cada petición espera a todas las que tiene delante. "
        "Cuando la espera pasa del timeout del usuario, el usuario se rinde y reintenta, y la "
        "petición que abandonó sigue en la cola. El servidor trabaja ahora en peticiones que nadie quiere.",
        "Es un fallo metaestable: el pico que lo empezó ya pasó, pero los reintentos y el trabajo "
        "muerto mantienen el servidor sobrecargado. Sigue roto hasta que algo descarta carga.",
        "Pon un límite a la cola: una petición que esperaría demasiado se rechaza en la puerta. "
        "Un no rápido es una respuesta; un timeout lento es un reintento.",
        "Descarta el trabajo que ya llega tarde: el plazo viaja con la petición, y se salta cuando "
        "no queda tiempo para responder. No se desperdicia nada en usuarios que se fueron.",
        "LIFO adaptativo: cuando la cola es larga, atiende primero las peticiones más nuevas. Esos "
        "usuarios siguen esperando y reciben respuesta rápida, mientras las viejas dan timeout y se descartan.",
    ),
    watch_for=(
        "FIFO sin límite: la cola pasa de miles y el servidor se pone naranja (DERROCHA).",
        "Cola con límite: la puerta se pone roja y rechaza, pero el trabajo sigue siendo para quien se fue.",
        "Salta lo tardío: no se desperdicia nada y se recupera, pero las respuestas tardan ~0.9 s.",
        "LIFO adaptativo: las respuestas tardan milisegundos incluso con 2.5x el tráfico.",
    ),
    build=(
        ("Go (net/http): ríndete antes si el cliente se fue o el plazo está cerca",
         "select {\n"
         "case <-r.Context().Done():\n"
         "    return // el cliente se fue: no hagas el trabajo\n"
         "default:\n"
         "}\n"
         "if dl, ok := r.Context().Deadline(); ok && time.Until(dl) < 100*time.Millisecond {\n"
         "    http.Error(w, \"too late\", http.StatusServiceUnavailable)\n"
         "    return\n"
         "}"),
        ("gRPC: los plazos viajan con la llamada",
         "stub.Get(request, timeout=1.0)  # el servidor ve el tiempo que queda y puede saltarla"),
        ("Envoy: descarta carga en la puerta",
         "circuit_breakers:\n"
         "  thresholds:\n"
         "  - max_pending_requests: 200   # una cola con límite: el resto recibe un 503 rápido"),
    ),
    checklist=(
        "Cada cola tiene un límite, medido en tiempo (cuánto puede esperar una petición), no solo en elementos.",
        "Los plazos se pasan hacia abajo, y el trabajo se salta cuando no queda tiempo suficiente.",
        "Los rechazos son rápidos y no provocan reintentos (o los reintentos gastan un presupuesto).",
        "Con sobrecarga, atiende primero las peticiones más nuevas (LIFO adaptativo) o usa CoDel.",
        "Mira el goodput (respuestas a tiempo), no solo el throughput: un servidor ocupado puede ser inútil.",
        "Pruébalo: envía 2-3x el tráfico durante 10 s y comprueba que se recupera solo.",
    ),
    refs=(
        Ref("AWS Builders' Library: Using load shedding to avoid overload",
            "https://aws.amazon.com/builders-library/using-load-shedding-to-avoid-overload/",
            "Goodput, trabajo desperdiciado y descartar carga antes de que sea tarde (en inglés)."),
        Ref("AWS Builders' Library: Avoiding insurmountable queue backlogs",
            "https://aws.amazon.com/builders-library/avoiding-insurmountable-queue-backlogs/",
            "Por qué los backlogs nunca se vacían solos, y LIFO con carga (en inglés)."),
        Ref("Metastable Failures in Distributed Systems (HotOS 2021)",
            "https://sigops.org/s/conferences/hotos/2021/papers/hotos21-s11-bronson.pdf",
            "El fallo que se mantiene solo cuando el detonante ya pasó (en inglés)."),
        Ref("Fail at Scale (Facebook, ACM Queue 2015)",
            "https://research.facebook.com/publications/fail-at-scale/",
            "Controlled delay (CoDel) y LIFO adaptativo para colas con carga (en inglés)."),
        Ref("Google SRE book: Handling Overload",
            "https://sre.google/sre-book/handling-overload/",
            "Limitación en el cliente y degradación controlada (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/overload/es/main.py y mira cómo la puerta rechaza en el pico.",
        "Haz la etapa 2 y mira cómo el objetivo Desperd. se pone verde y el servidor se recupera.",
        "Haz la etapa 3 y mira cómo el tiempo de respuesta baja a milisegundos.",
        "Prueba --set rate=90: ¿cuánto se puede acercar a la capacidad antes de que un pico lo rompa?",
    ),
)

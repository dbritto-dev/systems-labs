"""Laboratorio idempotency, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Claves de idempotencia"
SUMMARY = "Los pagos se reintentan. Cobra cada pago una sola vez, aunque llegue dos veces."
PARAMS = {"rate": "pagos por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"slow": "LENTO", "resets": "CORTES", "storm": "DOBLE", "calm": "CALMA"}
CAUSES = {
    "ledger_lock": "una migración bloquea la tabla del libro mayor",
    "disk_io": "un vecino ruidoso satura el disco de la base de datos",
    "vacuum": "autovacuum está reescribiendo la tabla de cobros",
    "failover": "la base de datos del libro mayor está haciendo failover",
    "lb_reset": "el balanceador corta conexiones a mitad de respuesta",
    "deploy_drain": "un despliegue cierra conexiones antes de que salgan las respuestas",
    "proxy_timeout": "un proxy da timeout y descarta las respuestas",
    "sdk_bug": "un SDK móvil nuevo envía cada pago dos veces",
    "double_click": "los usuarios hacen doble clic en Pagar en una página lenta",
    "proxy_retry": "un proxy reintenta peticiones por su cuenta",
}

STAGES = [
    StageText("Sin idempotencia",
              "Reto: un pago reintentado se cobra otra vez. Recuerda cada clave y repite su respuesta.",
              "Etapa 1: guarda el recibo de cada clave y devuélvelo de nuevo"),
    StageText("Repite respuestas",
              "Reto: un reintento que llega mientras el primero cobra, cobra dos veces. Reserva la clave.",
              "Etapa 2: reclama la clave con store.add antes de cobrar"),
    StageText("Claves reservadas",
              "Resuelto: cada pago se cobra una vez, y cada intento recibe el mismo recibo.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "charge() debe dar recibos"),
    "replay": GoalText("Repetidas ≥ 95%", "devuelve el recibo guardado"),
    "once": GoalText("Cobros dobles = 0", "reclama con store.add"),
    "same": GoalText("Mismo recibo", "los duplicados esperan"),
    "fast": GoalText("p99 < 500ms después", "responde rápido al duplicado"),
}

LEGEND = {"idle": "en reposo", "first_try": "primer intento", "retries": "reintento 1,2,3",
          "double": "cobrado dos veces", "answered": "respondido", "lost": "sin respuesta",
          "limit": "1 por pago", "incident": "incidente"}

STRINGS = {
    # incidentes
    "slow_start": "va lento, {seconds:.1f} s por cobro: {cause}",
    "slow_end": "vuelve a ir rápido",
    "resets_start": "pierde el {share:.0%} de las respuestas: {cause}",
    "resets_end": "las respuestas vuelven a llegar",
    "storm_start": "recibe el {share:.0%} de los pagos dos veces: {cause}",
    "storm_end": "los clientes vuelven a enviar cada pago una vez",
    "warn_double": "{n} pagos cobrados dos veces",
    # valores de los objetivos
    "none": "ninguno",
    "doubles": "{n}",
    # el panel
    "tile_doubles": "Dobles",
    "tile_replayed": "Repet.",
    "tile_retried": "Reint.",
    "bar_tries": "Intentos",
    "bar_charges": "Cobros",
    "limit": "1/pago",
    "head_doubles": "{n} pagos cobrados dos veces en 10 s",
    "head_slow": "El libro mayor va lento: se acumulan intentos",
    "head_ok": "Cada pago cobrado una vez",
    "state_slow": "LENTO",
    "state_double": "COBRO DOBLE",
    # el dibujo de clúster: la topología bajo la cuadrícula
    "pic_state": "servicio → claves · libro mayor: {state}",
    "note": "Los puntos son una muestra de intentos, más lentos (estético).",
    "subtitle": "por segundo, último 1 s",
    "title": "Pagos",
    # el dibujo relay: bajo la API de pagos (~14 letras como máximo)
    "relay_api": "API de pagos",
    "relay_replayed": "{n} repetidas",
    # errores en tu código
    "stuck": "un pago lleva más de {seconds:.0f} s: ¿charge() llega a devolver algo?",
}

LESSON = Lesson(
    title="Claves de idempotencia",
    one_liner="Una respuesta perdida o un cobro lento hacen que el cliente reintente. Sin clave, cada reintento es otro cobro.",
    learn=(
        "Las redes pierden respuestas después de hacer el trabajo: la tarjeta se cobró, pero el cliente "
        "nunca se enteró. El cliente no puede distinguirlo de un cobro que nunca ocurrió, así que "
        "reintenta. Cada reintento de una llamada no idempotente vuelve a hacer el trabajo.",
        "Una clave de idempotencia es un id único que el cliente envía con la petición y reutiliza en "
        "cada reintento. El servidor guarda el resultado bajo esa clave y, cuando la clave vuelve, "
        "devuelve el resultado guardado en lugar de hacer el trabajo otra vez.",
        "Comprobar y luego actuar es una carrera: si un reintento llega mientras el primer intento "
        "sigue en marcha, los dos ven 'aún sin resultado' y los dos cobran. Reclama la clave primero, "
        "en un solo paso atómico (INSERT ... ON CONFLICT DO NOTHING, Redis SET NX), y haz que los "
        "duplicados esperen el resultado o respondan 409.",
        "Las claves caducan. Guárdalas lo bastante para cubrir todos los reintentos (Stripe las guarda "
        "24 horas), y no más, para que el almacén no crezca sin fin.",
    ),
    watch_for=(
        "Sin idempotencia: cuando el libro mayor va lento, cada reintento es un segundo cobro (rojo).",
        "Repite respuestas: los reintentos tardíos reciben el recibo guardado, pero los que llegan "
        "mientras el primer intento sigue cobrando cobran dos veces.",
        "Claves reservadas: los duplicados esperan el recibo del primer intento; los cobros dobles se "
        "quedan en 0.",
    ),
    build=(
        ("PostgreSQL: reclama la clave y cobra en una transacción",
         "INSERT INTO idempotency_keys (key, status) VALUES ($1, 'in_progress')\n"
         "ON CONFLICT (key) DO NOTHING RETURNING key;\n"
         "-- sin fila: otro la tiene -> espera su respuesta o responde 409"),
        ("Redis: reclama con SET NX y una caducidad",
         "ok = await redis.set(f\"idem:{key}\", \"in-progress\", nx=True, ex=86400)\n"
         "if not ok:\n"
         "    return await wait_for_stored_response(key)  # o 409 Conflict"),
        ("HTTP: el cliente envía la misma clave en cada reintento",
         "POST /v1/charges\n"
         "Idempotency-Key: 5f0c1c2e-6f3a-4c7e-9b1a-2d4e8f9a0b1c"),
    ),
    checklist=(
        "Cada petición insegura (un POST que mueve dinero, envía correo, crea cosas) lleva clave.",
        "El cliente crea la clave una vez por operación y la reutiliza en cada reintento.",
        "Reclama la clave de forma atómica antes de hacer el trabajo; nunca comprobar y luego actuar.",
        "Guarda la respuesta completa (estado y cuerpo) y devuelve exactamente eso al repetir.",
        "Repetir con otro cuerpo bajo la misma clave es un error (422), no un cobro nuevo.",
        "Las claves caducan tras la ventana de reintentos más larga; límpialas.",
    ),
    refs=(
        Ref("Stripe: Idempotent requests",
            "https://docs.stripe.com/api/idempotent_requests",
            "Cómo una API de pagos real recibe, guarda y caduca las claves (en inglés)."),
        Ref("Stripe engineering: Designing robust and predictable APIs with idempotency",
            "https://stripe.com/blog/idempotency",
            "Por qué las respuestas perdidas hacen peligrosos los reintentos, y cómo lo arreglan las claves (en inglés)."),
        Ref("IETF draft: The Idempotency-Key HTTP header field",
            "https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/",
            "La cabecera, y qué debe responder el servidor a un duplicado simultáneo (409) (en inglés)."),
        Ref("AWS Builders' Library: Making retries safe with idempotent APIs",
            "https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/",
            "Tokens de petición del cliente, y qué devolver al repetir (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/idempotency/es/main.py y mira cómo la tarjeta Repet. se pone verde.",
        "Luego mira el siguiente libro mayor lento: ¿de dónde salen ahora los cobros dobles?",
        "Haz la etapa 2 y mira cómo desaparecen los dobles, aunque los clientes lo envíen todo dos veces.",
    ),
)

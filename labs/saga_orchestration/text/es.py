"""Laboratorio saga_orchestration, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Sagas"
SUMMARY = "Un pedido pasa por pagos, inventario y envíos. Nunca lo dejes a medias."
PARAMS = {"rate": "pedidos por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"timeouts": "LENTO", "oom": "LENTO", "stockout": "VACÍO", "shipping": "CAÍDA", "crash": "SE CAE",
         "back": "VUELVE", "calm": "CALMA"}
CAUSES = {
    "psp_overload": "el proveedor de pagos está saturado; las respuestas llegan tarde",
    "psp_network": "se pierden paquetes entre nosotros y el proveedor de pagos",
    "inventory_gc": "pausas largas del recolector de basura en el servicio de inventario",
    "inventory_lock": "una migración bloquea la tabla de inventario",
    "carrier_slow": "la API de reservas de la transportista va lenta",
    "carrier_lb": "el balanceador de la transportista descarta respuestas",
    "carrier_slow_oom": "la API de la transportista va lenta; las sagas en espera llenan la memoria del orquestador",
    "flash_sale": "una oferta relámpago agota los artículos más populares",
    "inventory_sync": "una sincronización de inventario errónea muestra existencias que no hay",
    "warehouse_count": "un recuento del almacén descubre que faltan artículos",
    "carrier_outage": "la transportista tiene una caída",
    "carrier_cert": "caducó el certificado TLS de la transportista",
    "carrier_ratelimit": "la transportista limita las peticiones de nuestra cuenta",
    "deploy": "un despliegue reinicia el orquestador",
    "oom_kill": "el sistema mata al orquestador por falta de memoria",
    "node_evicted": "vacían el nodo del orquestador por mantenimiento",
}

STAGES = [
    StageText("Sin deshacer",
              "Reto: un paso fallido deja la tarjeta cobrada y los artículos retenidos. Compensa.",
              "Etapa 1: ante StepFailed, deshaz los pasos hechos, del último al primero"),
    StageText("Compensaciones",
              "Reto: timeouts y caídas aún dejan pedidos a medias. Haz las sagas reanudables.",
              "Etapa 2: claves en cada llamada, reintentos, un registro, recover()"),
    StageText("Sagas reanudables",
              "Resuelto: cada pedido termina completo o deshecho del todo, incluso tras una caída.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "place() debe acabar pedidos"),
    "rolled": GoalText("Deshechos 100%", "deshaz pasos, último primero"),
    "consistent": GoalText("A medias = 0", "claves, reintentos, recover"),
    "once": GoalText("Cobros dobles = 0", "cobra con key=saga_id"),
    "completed": GoalText("Completos ≥ 95%", "reintenta con la misma clave"),
    "fast": GoalText("p99 fin < 1s después", "recupera sin bloquear"),
}

LEGEND = {"idle": "en reposo", "step": "paso", "retry": "tras un timeout", "undo": "compensación",
          "done": "completo", "orphan": "a medias", "limit": "pedidos", "incident": "incidente"}

STRINGS = {
    # incidentes
    "timeouts_start": "el {share:.0%} de las llamadas da timeout: {cause}",
    "timeouts_end": "las respuestas vuelven a llegar a tiempo",
    "oom_start": "el {share:.0%} de las reservas de envío da timeout: {cause}",
    "oom_end": "la transportista vuelve a responder a tiempo",
    "stockout_start": "el {share:.0%} de los pedidos no tiene existencias: {cause}",
    "stockout_end": "vuelve a haber existencias",
    "shipping_start": "la transportista rechaza el {share:.0%} de las reservas: {cause}",
    "shipping_end": "la transportista vuelve a aceptar reservas",
    "crash_start": "el orquestador se cae a mitad de la saga: {cause}",
    "crash_end": "arranca un orquestador nuevo; se ejecuta recover()",
    "warn_crash": "el orquestador se queda sin memoria y se cae a mitad de la saga",
    "warn_orphans": "{n} pedidos quedaron a medias",
    "warn_doubles": "{n} pedidos cobrados dos veces",
    # valores de los objetivos
    "none": "ninguno",
    # el panel
    "tile_orphans": "A medias",
    "tile_doubles": "Dobles",
    "tile_done": "Hechos",
    "bar_steps": "Pasos",
    "bar_undos": "Deshacer",
    "bar_sagas": "Terminan",
    "limit": "pedidos",
    "head_orphans": "{n} pedidos a medias en 10 s",
    "head_down": "Orquestador caído: pedidos esperan",
    "head_failing": "Fallan pasos: se deshacen",
    "head_ok": "Cada pedido completo o deshecho",
    # los dibujos
    "state_down": "REINICIANDO",
    "state_orphans": "A MEDIAS",
    "state_timeouts": "TIMEOUTS",
    "state_failing": "FALLAN PASOS",
    "pic_state": "pedidos → pagos · inventario · envíos: {state}",
    "note": "Los puntos son una muestra de llamadas, más lentos (estético).",
    "subtitle": "por segundo, último 1 s",
    "title": "Sagas",
    # errores en tu código
    "stuck": "una saga lleva más de {seconds:.0f} s: ¿place() llega a devolver algo?",
}

LESSON = Lesson(
    title="Sagas",
    one_liner="Un pedido, tres servicios, ninguna transacción compartida: cada paso hecho debe "
              "deshacerse cuando uno posterior falla, incluso con timeouts y caídas.",
    learn=(
        "Una saga es una secuencia de transacciones locales, una por servicio, cada una con una acción "
        "compensatoria que la deshace en la práctica: reembolsar el cobro, liberar el inventario, "
        "cancelar la reserva de envío. No hay vuelta atrás entre servicios, así que el orquestador "
        "ejecuta las compensaciones él mismo, en orden inverso, cuando falla un paso posterior.",
        "Un timeout no es un fallo: el paso pudo haberse hecho y solo se perdió la respuesta. Si solo "
        "deshaces los pasos cuya respuesta recibiste, el que dio timeout se queda hecho. Deshazlo igual "
        "por su clave de idempotencia (deshacer lo que nunca pasó no hace nada), o reinténtalo con la "
        "misma clave para saber qué pasó.",
        "El propio orquestador puede caerse a mitad de una saga (un despliegue, falta de memoria). Lo "
        "que tenía en memoria se pierde, así que guarda el estado de cada saga en almacenamiento "
        "duradero antes de cada fase (escritura anticipada), y una instancia nueva reanuda cada saga "
        "sin terminar desde ahí: hacia delante si estaba en marcha, hacia atrás si estaba compensando.",
        "Reanudar repite pasos que quizá ya ocurrieron, así que cada paso y cada compensación deben ser "
        "idempotentes, con una clave basada en el id de la saga. Eso hace seguros los reintentos y la "
        "recuperación: la misma clave nunca cobra dos veces.",
    ),
    watch_for=(
        "Sin deshacer: cuando falla la transportista, hay clientes cobrados sin pedido y artículos "
        "retenidos (rojo).",
        "Compensaciones: los pasos fallidos se deshacen (naranja), pero un paso que dio timeout y sí "
        "ocurrió, o una saga que la caída cortó, queda a medias.",
        "Sagas reanudables: tras la caída, un orquestador nuevo termina cada saga; a medias se queda en 0.",
    ),
    build=(
        ("Un paso del orquestador: escribe antes, luego llama con el id de la saga como clave",
         "await log.save(saga_id, {\"order\": order, \"status\": \"running\"})\n"
         "charge = await payments.charge(order, idempotency_key=f\"{saga_id}:charge\")\n"
         "# si falla: guarda status=compensating, y luego refund/release/cancel con las mismas claves"),
        ("PostgreSQL: el registro de sagas, y las que quedan por reanudar tras reiniciar",
         "CREATE TABLE saga (id text PRIMARY KEY, status text NOT NULL, state jsonb NOT NULL,\n"
         "                   updated_at timestamptz NOT NULL DEFAULT now());\n"
         "SELECT id, state FROM saga WHERE status IN ('running', 'compensating');"),
        ("Temporal: un motor de flujos guarda la saga por ti; compensaciones en orden inverso",
         "try:\n"
         "    await workflow.execute_activity(charge, order, ...)\n"
         "    compensations.append(refund)\n"
         "    ...\n"
         "except ActivityError:\n"
         "    for undo in reversed(compensations):\n"
         "        await workflow.execute_activity(undo, order, ...)"),
    ),
    checklist=(
        "Cada paso tiene su compensación, y las compensaciones se ejecutan en orden inverso.",
        "Una compensación no puede fallar para siempre: reinténtala hasta que funcione (y alerta si sigue fallando).",
        "Cada paso y cada compensación lleva una clave de idempotencia derivada del id de la saga.",
        "Un timeout significa 'no se sabe': reintenta con la misma clave, o compensa por clave; nunca lo ignores.",
        "Guarda el estado de la saga antes de cada fase; reanuda las sagas sin terminar al arrancar.",
        "Marca la saga 'compensating' antes de deshacer nada, para que un reinicio nunca vuelva a ir hacia delante.",
    ),
    refs=(
        Ref("Garcia-Molina and Salem: Sagas (1987)",
            "https://www.cs.cornell.edu/andru/cs711/2002fa/reading/sagas.pdf",
            "El artículo original: transacciones largas como pasos con compensaciones (en inglés)."),
        Ref("microservices.io: Pattern: Saga",
            "https://microservices.io/patterns/data/saga.html",
            "Orquestación y coreografía, con un ejemplo de pedidos (en inglés)."),
        Ref("Azure Architecture Center: Saga distributed transactions pattern",
            "https://learn.microsoft.com/es-es/azure/architecture/patterns/saga",
            "Pasos compensables, pivote y reintentables, y las anomalías de datos a prever."),
        Ref("AWS Prescriptive Guidance: Saga orchestration pattern",
            "https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/saga-orchestration.html",
            "Un orquestador con Step Functions, y compensaciones idempotentes (en inglés)."),
        Ref("Temporal: Saga pattern made easy",
            "https://temporal.io/blog/saga-pattern-made-easy",
            "Un motor de flujos que guarda y reanuda las sagas por ti (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/saga_orchestration/es/main.py y mira las compensaciones naranjas cuando falla la transportista.",
        "Luego mira la siguiente caída: ¿qué pedidos quedan a medias ahora, y por qué?",
        "Haz la etapa 2 y mira cómo un orquestador nuevo termina cada saga que la caída cortó.",
    ),
)

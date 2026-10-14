"""Laboratorio transactional_outbox, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Bandeja de salida transaccional"
SUMMARY = "Guarda cada pedido y avísalo a envíos: sin perder eventos, sin inventarlos, sin enviar dos veces."
PARAMS = {"rate": "pedidos por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"crash": "MUERE", "broker": "CAÍDA", "locks": "TRABAS", "relay": "RELÉ", "rebalance": "REPART",
         "calm": "CALMA"}
CAUSES = {
    "oom_kill": "una fuga de memoria agota la RAM y el sistema mata el servicio de pedidos",
    "deploy_kill": "un despliegue mata los procesos sin un apagado ordenado",
    "node_lost": "se pierde el nodo donde corre el servicio de pedidos",
    "spot_reclaim": "la nube recupera sus máquinas de subasta",
    "leader_lost": "muere un nodo del intermediario y sus particiones se quedan sin líder",
    "rolling_upgrade": "una actualización escalonada del intermediario sale mal",
    "cert_expired": "el certificado TLS del intermediario ha caducado",
    "disk_full": "el disco del intermediario está lleno y rechaza escrituras",
    "migration_lock": "una migración retiene bloqueos: las consolidaciones agotan su timeout",
    "batch_deadlock": "un proceso nocturno se interbloquea con los pedidos",
    "db_failover": "la base de datos de pedidos conmuta a su réplica a mitad de una consolidación",
    "hot_row": "una oferta relámpago martillea una fila de existencias: fallos de serialización",
    "relay_oom": "el sistema mata el relé, sin memoria por un lote enorme",
    "relay_deploy": "un despliegue reinicia el relé una y otra vez",
    "lease_lost": "el relé pierde una y otra vez su concesión de líder",
    "consumer_deploy": "envíos despliega: su grupo de consumidores se reparte de nuevo",
    "autoscale": "el autoescalado añade y quita consumidores de envíos",
    "missed_heartbeat": "un consumidor de envíos lento deja de dar señales de vida y lo echan del grupo",
}

STAGES = [
    StageText("Doble escritura",
              "Reto: una muerte entre la base de datos y el intermediario pierde o inventa eventos.",
              "Etapa 1: escribe el evento en la bandeja de salida, en la transacción del pedido"),
    StageText("Bandeja de salida",
              "Reto: tras una muerte el relé vuelve a publicar, y hay pedidos enviados dos veces.",
              "Etapa 2: anota el id de cada evento en la transacción del envío"),
    StageText("Consumidor idempotente",
              "Resuelto: cada pedido guardado se envía exactamente una vez, y nada más.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "envía cada pedido guardado"),
    "lost": GoalText("Perdidos = 0", "escribe el evento en la tx"),
    "phantom": GoalText("Fantasmas = 0", "publica solo desde el relé"),
    "dup": GoalText("Envíos dobles = 0", "descarta por id de evento"),
    "lag": GoalText("Retraso p99 < 3s tras", "relé por lotes, sin pausas"),
}

LEGEND = {"idle": "en reposo", "event": "pedido, evento", "republished": "publicado otra vez",
          "twice": "enviado dos veces", "bad": "perdido o fantasma", "shipped": "enviado",
          "skipped": "descartado", "limit": "ritmo de pedidos", "incident": "incidente"}

STRINGS = {
    # incidentes
    "crash_start": "el servicio de pedidos muere cada {every:.1f} s: {cause}",
    "crash_end": "el servicio de pedidos sigue en pie otra vez",
    "broker_start": "el intermediario rechaza todos los mensajes: {cause}",
    "broker_end": "el intermediario vuelve",
    "locks_start": "falla el {share:.0%} de las consolidaciones de pedidos: {cause}",
    "locks_end": "las consolidaciones vuelven a pasar",
    "relay_start": "el relé muere cada {every:.1f} s: {cause}",
    "relay_end": "el relé sigue en pie otra vez",
    "rebalance_start": "envíos se reparte de nuevo cada {every:.1f} s: {cause}",
    "rebalance_end": "el grupo de consumidores de envíos vuelve a estar estable",
    "warn_lost": "{n} pedidos guardados nunca llegaron a envíos",
    "warn_twice": "{n} pedidos enviados dos veces",
    # valores de los objetivos
    "count": "{n}",
    "on_the_way": "{n} en camino",
    # el panel
    "tile_lost": "Perdid.",
    "tile_phantom": "Fantasma",
    "tile_twice": "Dobles",
    "bar_saved": "Guardados",
    "bar_published": "Publicados",
    "bar_shipped": "Enviados",
    "limit": "pedidos/s",
    "head_phantom": "{n} eventos fantasma en 10 s",
    "head_lost": "{n} eventos perdidos en 10 s",
    "head_twice": "{n} pedidos enviados dos veces en 10 s",
    "head_outbox": "{n} eventos esperan en la bandeja",
    "head_ok": "Cada pedido guardado, enviado una vez",
    # los dibujos
    "state_restart": "REINICIANDO",
    "state_broker": "INTERMEDIARIO CAÍDO",
    "state_relay": "RELÉ CAÍDO",
    "state_rebalance": "REPARTIENDO",
    "state_locks": "INTERBLOQUEOS",
    "lane_state": "{state} · bandeja {n}",
    "pic_state": "servicio·bd·relé / envíos·interm.: {state}",
    "note": "Los puntos son una muestra de pedidos y eventos, más lentos (estético).",
    "subtitle": "por segundo, último 1 s",
    "title": "Eventos",
    # errores en tu código
    "stuck": "un pedido lleva más de {seconds:.0f} s: ¿place_order() llega a devolver algo?",
}

LESSON = Lesson(
    title="Bandeja de salida transaccional",
    one_liner="Escribir en una base de datos y en un intermediario de mensajes son dos escrituras sin "
              "transacción entre ellas. Haz una sola escritura, publica a partir de ella, y que el "
              "consumidor descarte las repeticiones.",
    learn=(
        "Una doble escritura guarda el pedido y publica el evento en dos sistemas. No hay transacción "
        "que abarque los dos, así que cualquier fallo entre medias los separa: el proceso muere después "
        "de consolidar (el evento se pierde), el intermediario está caído (el evento se pierde), o el "
        "evento sale antes de una consolidación que luego falla (un fantasma: envíos manda un pedido que "
        "no existe).",
        "La bandeja de salida transaccional escribe el evento como una fila de una tabla outbox, en la "
        "misma transacción de base de datos que el pedido. O se guardan los dos o ninguno. Un relé aparte "
        "lee las filas sin enviar, las publica y las marca como enviadas. Es el único camino al "
        "intermediario.",
        "El relé publica primero y marca después. Si muere entre medias, la fila se publica otra vez al "
        "reiniciarse: entrega al menos una vez. Marcar primero sería como mucho una vez, y perdería "
        "eventos. Los repartos del grupo de consumidores también vuelven a entregar. Los duplicados son "
        "normales; cuenta con ellos.",
        "Un consumidor idempotente anota el id de cada evento que ha tratado en su propia base de datos, en "
        "la misma transacción que el efecto (el envío), y salta un id que ya ha visto. Entrega al menos una "
        "vez más un consumidor idempotente es exactamente una vez en efecto.",
        "El retraso es el precio: un evento sale cuando el relé vuelve a consultar. Consulta a menudo, "
        "publica por lotes y, tras una caída del intermediario, vacía deprisa lo acumulado. La captura de "
        "cambios (Debezium leyendo el registro de la base de datos) es un relé que no consulta.",
    ),
    watch_for=(
        "Doble escritura: cada muerte justo después de publicar deja un fantasma (rojo); una caída del "
        "intermediario pierde el evento de cada pedido guardado durante ella.",
        "Bandeja de salida: nada se pierde ni se inventa; la bandeja se llena mientras el intermediario "
        "está caído y se vacía después; pero las muertes y los repartos envían algunos pedidos dos veces "
        "(naranja oscuro).",
        "Consumidor idempotente: las repeticiones siguen llegando (gris en envíos), y se descartan.",
    ),
    build=(
        ("PostgreSQL: el pedido y su evento en una transacción",
         "BEGIN;\n"
         "INSERT INTO orders (id, customer, total) VALUES ($1, $2, $3);\n"
         "INSERT INTO outbox (id, topic, payload) VALUES ($4, 'orders', $5);\n"
         "COMMIT;"),
        ("El relé: publica y luego marca (SKIP LOCKED deja que varios relés compartan la tabla)",
         "rows = SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED;\n"
         "for row in rows: producer.send(row.topic, key=row.aggregate_id, value=row.payload)\n"
         "producer.flush()\n"
         "UPDATE outbox SET sent_at = now() WHERE id = ANY($ids);"),
        ("El consumidor: descarta duplicados en la misma transacción que el efecto",
         "BEGIN;\n"
         "INSERT INTO processed_events (event_id) VALUES ($1) ON CONFLICT DO NOTHING;\n"
         "-- ninguna fila insertada: ya visto, COMMIT y saltar\n"
         "INSERT INTO shipments (order_id) VALUES ($2);\n"
         "COMMIT;"),
    ),
    checklist=(
        "Nunca publiques desde una petición que también escribe en la base de datos: escribe una fila en "
        "la bandeja de salida.",
        "La fila de la bandeja y la fila del negocio se consolidan en una sola transacción.",
        "El relé publica, espera la confirmación del intermediario y luego marca las filas como enviadas.",
        "Cada evento tiene un id único, y los consumidores descartan duplicados por él en la misma "
        "transacción que su efecto.",
        "Guarda los ids tratados al menos mientras pueda haber reentregas; borra las filas ya enviadas.",
        "Alerta por el tamaño de la bandeja y por la edad de la fila sin enviar más antigua.",
        "Publica con el id del agregado como clave, para que los eventos de un pedido mantengan su orden.",
    ),
    refs=(
        Ref("microservices.io: Transactional outbox",
            "https://microservices.io/patterns/data/transactional-outbox.html",
            "El patrón, sus fuerzas y el relé (consulta periódica o lectura del registro) (en inglés)."),
        Ref("microservices.io: Idempotent consumer",
            "https://microservices.io/patterns/communication-style/idempotent-consumer.html",
            "Anotar los ids de los mensajes tratados para que los duplicados no hagan daño (en inglés)."),
        Ref("Confluent: Understanding the dual write problem",
            "https://www.confluent.io/blog/dual-write-problem/",
            "Por qué escribir en una base de datos y en Kafka sin transacción pierde o inventa datos "
            "(en inglés)."),
        Ref("AWS Prescriptive Guidance: Transactional outbox pattern",
            "https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html",
            "La bandeja de salida en AWS, con el tratamiento de duplicados en el consumidor (en inglés)."),
        Ref("Debezium: Outbox event router",
            "https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html",
            "Un relé hecho con captura de cambios: lee el registro de la base de datos en vez de consultar "
            "(en inglés)."),
        Ref("Confluent: Message delivery guarantees",
            "https://docs.confluent.io/kafka/design/delivery-semantics.html",
            "Como mucho una vez, al menos una vez y exactamente una vez, y de dónde sale cada una (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/transactional_outbox/es/main.py y mira cómo Perdid. y Fantasma se quedan en 0.",
        "Luego mira la siguiente muerte: ¿por qué envíos recibe ahora algunos pedidos dos veces?",
        "Haz la etapa 2 y mira cómo las repeticiones se vuelven grises: descartadas, nunca enviadas dos veces.",
    ),
)

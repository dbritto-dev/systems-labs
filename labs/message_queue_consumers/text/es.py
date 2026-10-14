"""Laboratorio message_queue_consumers, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Consumidores de una cola de mensajes"
SUMMARY = "Los workers toman trabajos de una cola. No pierdas ninguno, haz cada uno una vez y aparta el veneno."
PARAMS = {"rate": "trabajos enviados por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"crash": "CAEN", "slow": "LENTO", "poison": "VENENO", "blip": "CAÍDA", "calm": "CALMA"}
CAUSES = {
    "deploy": "un despliegue mata workers sin dejarlos terminar",
    "oom": "una fuga de memoria hace que el sistema mate workers por OOM",
    "spot": "se recuperan las instancias spot donde corren los workers",
    "node_drain": "Kubernetes vacía los nodos donde corren los workers",
    "migration": "una migración bloquea la tabla de facturas",
    "throttling": "el proveedor de correo nos limita las peticiones",
    "big_exports": "los clientes piden exportaciones enormes",
    "cold_cache": "la caché del servicio de abajo se reinició vacía",
    "staging_ids": "un despliegue de un productor envía ids de staging: las búsquedas esperan hasta su timeout",
    "schema_change": "un productor renombró un campo que todos los trabajos necesitan",
    "deleted_records": "los mensajes apuntan a registros que se borraron",
    "truncated": "un bug de un productor recorta los mensajes",
    "failover": "la base de datos del servicio de abajo está haciendo failover",
    "dns": "un cambio de DNS deja inalcanzable el servicio de abajo",
    "cert_rotation": "el servicio de abajo rotó mal su certificado",
    "conn_reset": "un balanceador corta todas las conexiones",
}

STAGES = [
    StageText("Confirma al recibir",
              "Reto: un trabajo que cae o falla tras confirmarlo se pierde. Confirma después del trabajo.",
              "Etapa 1: borra tras el éxito de handle(); latido mientras corre"),
    StageText("Confirma al terminar",
              "Reto: los mensajes veneno fallan siempre y nunca salen de la cola. Apártalos en una DLQ.",
              "Etapa 2: al fallar, espera más; tras MAX_RECEIVES, a la DLQ"),
    StageText("Reintentos + DLQ",
              "Resuelto: ningún trabajo perdido, ninguno doble a la vez, y el veneno espera en la DLQ.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "process() debe confirmar"),
    "lost": GoalText("Perdidos = 0", "confirma al terminar"),
    "dups": GoalText("Duplicados ≤ 1%", "latido mientras trabajas"),
    "age": GoalText("Edad en cola p99 < 1s", "aparta el veneno en la DLQ"),
    "dlq": GoalText("DLQ: solo veneno", "espera más, luego aparta"),
}

LEGEND = {"idle": "en reposo", "first": "1.ª entrega", "redelivered": "reentregado", "duplicate": "hecho dos veces",
          "acked": "confirmado", "lost": "perdido", "parked": "en la DLQ", "limit": "enviados",
          "incident": "incidente"}

STRINGS = {
    # incidentes
    "crash_start": "los procesos workers caen a mitad de trabajo: {cause}",
    "crash_end": "los workers vuelven a aguantar",
    "slow_start": "hace que el 10% de los trabajos tarde {seconds:.1f} s, más que el timeout de 2 s: {cause}",
    "slow_end": "el servicio de abajo vuelve a ir rápido",
    "poison_start": "el {share:.0%} de los mensajes nuevos son veneno: {cause}",
    "poison_end": "los productores vuelven a enviar mensajes buenos",
    "blip_start": "falla cada llamada al servicio de abajo: {cause}",
    "blip_end": "el servicio de abajo vuelve a responder",
    "warn_lost": "{n} trabajos perdidos",
    "warn_stuck": "{n} mensajes siguen en la cola",
    # valores de los objetivos
    "none": "ninguno",
    "parked": "{n}/{of}",
    "good_parked": "{n} buenos",
    # el panel
    "tile_lost": "Perdidos",
    "tile_dups": "Dobles",
    "tile_age": "Edad p99",
    "bar_sent": "Enviados",
    "bar_tries": "Trabajo",
    "bar_out": "Acabados",
    "limit": "enviados",
    "head_lost": "{n} trabajos perdidos en 10 s",
    "head_dups": "el {share:.0%} de los trabajos se hace dos veces",
    "head_old": "El mensaje más viejo tiene {seconds:.0f} s",
    "head_crash": "Los workers caen a mitad de trabajo",
    "head_slow": "Los trabajos lentos duran más que su visibilidad",
    "head_poison": "Los mensajes veneno siguen fallando",
    "head_blip": "Todos los trabajos fallan un momento",
    "head_ok": "Cada trabajo hecho una vez",
    "stat_done": "hechos",
    "stat_lost": "perdidos",
    "stat_queued": "en cola",
    "stat_dlq": "DLQ",
    "stat_age": "edad p99",
    "title": "Trabajos",
    "subtitle": "por segundo, último 1 s",
    # los dibujos
    "state_down": "{n} CAÍDOS",
    "state_slow": "LENTO",
    "state_poison": "VENENO",
    "state_blip": "FALLANDO",
    "state_old": "MENSAJES VIEJOS",
    "pic_state": "cola → workers → DLQ: {state}",
    "note": "Los puntos son una muestra de trabajos, más lentos (estético).",
    # errores en tu código
    "stuck": "una llamada a process() lleva más de {seconds:.0f} s: arranca el latido como tarea, "
             "¿y llega a terminar?",
}

LESSON = Lesson(
    title="Consumidores de una cola de mensajes",
    one_liner="Una cola presta cada trabajo a un worker durante un rato. Cuándo confirmar, cómo retenerlo y "
              "cuándo rendirse.",
    learn=(
        "Una cola como SQS no regala un mensaje: lo presta. Un mensaje recibido queda oculto para los demás "
        "workers durante su timeout de visibilidad; si no se borra (se confirma) antes, la cola se lo da a "
        "otro worker. Eso la hace «al menos una vez»: no se pierde nada, pero cualquier cosa puede llegar dos veces.",
        "Confirmar al recibir lo convierte en «como mucho una vez»: un worker que cae a mitad de trabajo (un "
        "despliegue, un OOM) o un trabajo que falla pierde el trabajo para siempre. Confirma después del "
        "trabajo: una caída o un fallo deja el mensaje en la cola, y vuelve.",
        "Pero un trabajo que tarda más que el timeout de visibilidad vuelve mientras el primer worker sigue "
        "con él: dos workers hacen el mismo trabajo. Mantén un latido: alarga la visibilidad cada pocos "
        "segundos mientras trabajas, y para cuando termines o mueras. Haz el trabajo idempotente de todos "
        "modos: los duplicados siguen pasando.",
        "Algunos mensajes nunca salen bien (un despliegue malo de un productor, un registro que falta). Si se "
        "reintentan para siempre se comen los workers, y la edad del mensaje más viejo crece sin fin. "
        "Reintenta unas pocas veces con backoff (así pasa una caída breve) y después mueve el mensaje a una "
        "cola de mensajes muertos (DLQ) para que lo mire una persona.",
    ),
    watch_for=(
        "Confirma al recibir: cuando los workers caen o una caída breve hace fallar todo, se pierden "
        "trabajos (rojo).",
        "Confirma al terminar: nada perdido, los trabajos lentos no se hacen dos veces, pero el veneno nunca "
        "sale de la cola: sigue ahí minutos después, y la DLQ sigue vacía.",
        "Reintentos + DLQ: el veneno va a la DLQ tras MAX_RECEIVES intentos (morado), y una caída breve no "
        "aparta nada.",
    ),
    build=(
        ("SQS: una política de redrive mueve un mensaje a la DLQ tras maxReceiveCount entregas",
         "aws sqs set-queue-attributes --queue-url $QUEUE --attributes '{\n"
         "  \"VisibilityTimeout\": \"30\",\n"
         "  \"RedrivePolicy\": \"{\\\"deadLetterTargetArn\\\":\\\"'$DLQ_ARN'\\\",\\\"maxReceiveCount\\\":\\\"5\\\"}\"}'"),
        ("boto3: latido mientras corre el trabajo, borrar cuando termina",
         "while not job.done():\n"
         "    sqs.change_message_visibility(QueueUrl=url, ReceiptHandle=msg[\"ReceiptHandle\"],\n"
         "                                  VisibilityTimeout=30)\n"
         "    job.wait(timeout=10)\n"
         "sqs.delete_message(QueueUrl=url, ReceiptHandle=msg[\"ReceiptHandle\"])"),
        ("RabbitMQ: confirmaciones manuales, y un exchange de mensajes muertos para los rechazados",
         "channel.queue_declare(\"jobs\", arguments={\"x-dead-letter-exchange\": \"jobs.dlx\"})\n"
         "channel.basic_consume(\"jobs\", on_message, auto_ack=False)\n"
         "# si sale bien: ch.basic_ack(tag); si es veneno: ch.basic_nack(tag, requeue=False)"),
    ),
    checklist=(
        "Confirma (borra) solo cuando el trabajo está hecho, nunca al recibir.",
        "Pon el timeout de visibilidad por encima del tiempo normal de un trabajo, y usa un latido para los largos.",
        "Para el latido cuando el trabajo acaba, falla o el proceso muere.",
        "Haz cada trabajo idempotente: «al menos una vez» quiere decir que algunos se ejecutan dos veces.",
        "Reintenta los fallos con backoff exponencial y jitter, un número limitado de veces.",
        "Manda lo que sigue fallando a una DLQ, pon una alarma en ella, y ten una forma de devolverlo a la cola.",
        "Pon la alarma en la edad del mensaje más viejo, no solo en la longitud de la cola.",
    ),
    refs=(
        Ref("Amazon SQS: Visibility timeout",
            "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html",
            "Cómo se oculta un mensaje recibido, y cuándo vuelve."),
        Ref("Amazon SQS: ChangeMessageVisibility",
            "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ChangeMessageVisibility.html",
            "La llamada detrás de un latido (y de la espera antes de un reintento)."),
        Ref("Amazon SQS: Dead-letter queues",
            "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html",
            "maxReceiveCount, la política de redrive, y cómo devolver mensajes a la cola."),
        Ref("AWS Builders' Library: Timeouts, retries, and backoff with jitter",
            "https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/",
            "Por qué los reintentos necesitan backoff, jitter y un límite."),
        Ref("Google Cloud Pub/Sub: Handling message failures",
            "https://cloud.google.com/pubsub/docs/handling-failures",
            "Las mismas ideas en otro broker: políticas de reintento y temas de mensajes muertos."),
        Ref("RabbitMQ: Consumer acknowledgements",
            "https://www.rabbitmq.com/docs/confirms",
            "Confirmación automática o manual, y qué pasa con los mensajes sin confirmar."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/message_queue_consumers/es/main.py y mira la próxima caída de workers: nada "
        "se vuelve rojo.",
        "Quita el latido un minuto y mira un servicio lento: los trabajos se hacen dos veces.",
        "Haz la etapa 2 y mira cómo el veneno va a la DLQ (morado), mientras una caída breve no aparta nada.",
    ),
)

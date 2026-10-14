"""Laboratorio webhook_delivery, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Entrega de webhooks"
SUMMARY = "Envía cada evento a 20 destinos de clientes, en orden, aunque algunos estén caídos o lentos."
PARAMS = {"rate": "eventos creados por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"down": "CAÍDA", "hang": "CUELGA", "slow": "LENTO", "poison": "VENENO", "burst": "PICO",
         "back": "VUELVE", "calm": "CALMA"}
CAUSES = {
    "deploy": "su despliegue responde 503 hasta que termina",
    "cert_expired": "su certificado TLS caducó: falla cada saludo TLS",
    "maintenance": "están en modo mantenimiento y responden 503",
    "crashloop": "su servicio de webhooks se reinicia sin parar: rechaza las conexiones",
    "dns": "un cambio de DNS apunta su dominio a una IP vieja: las conexiones se cuelgan",
    "firewall": "una regla nueva de su cortafuegos descarta nuestros paquetes sin avisar",
    "allowlist": "olvidaron nuestras IP nuevas en su lista de permitidas: se descartan los paquetes",
    "no_backends": "su balanceador acepta conexiones, pero no hay ningún servidor detrás",
    "database": "su base de datos va con dificultad: cada webhook tarda segundos",
    "sync_calls": "llaman a una API lenta antes de responder cada webhook",
    "table_lock": "una migración larga bloquea su tabla de pedidos",
    "swapping": "su único servidor se quedó sin memoria y está paginando a disco",
    "emoji": "un emoji en el nombre de un comprador rompe su analizador",
    "null_field": "un código de descuento nulo hace fallar su manejador",
    "currency": "los pedidos en una moneda nueva rompen su código",
    "big_payload": "los pedidos con cientos de artículos superan su límite de tamaño (413)",
    "flash_sale": "una oferta relámpago",
    "black_friday": "empieza el Black Friday",
    "bulk_import": "un comercio importa pedidos en masa",
    "newsletter": "un boletín manda a todos a la tienda a la vez",
}

STAGES = [
    StageText("Un solo envío",
              "Reto: un destino caído pierde sus eventos; uno colgado acapara los workers. Reintenta.",
              "Etapa 1: timeout en cada POST; reintenta con backoff + jitter"),
    StageText("Reintentos",
              "Reto: un destino muerto aún se come los workers, y los eventos llegan desordenados.",
              "Etapa 2: una cola por destino, en orden por clave; pausa al fallar"),
    StageText("Cola por destino",
              "Resuelto: nada perdido, cada pedido en orden, y un destino muerto no frena a los demás.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "entrega en next()"),
    "lost": GoalText("Perdidos = 0", "reintenta con backoff"),
    "order": GoalText("Desordenados = 0", "de cada pedido, uno a la vez"),
    "p99": GoalText("p99 sanos < 1s", "una cola + tope por destino"),
    "waste": GoalText("Desperdicio ≤ 10%", "pausa el destino que falla"),
}

LEGEND = {"idle": "en reposo", "first": "1.er intento", "retry": "reintento", "delivered": "entregado",
          "out_of_order": "desordenado", "failed": "fallido", "gave_up": "abandonado", "limit": "eventos creados",
          "incident": "incidente"}

STRINGS = {
    # incidentes
    "down_start": "el destino #{n} está caído: {cause}",
    "down_end": "el destino #{n} vuelve a responder",
    "hang_start": "el destino #{n} no responde nunca: {cause}",
    "hang_end": "el destino #{n} vuelve a responder",
    "slow_start": "el destino #{n} tarda 2,5-8 s en responder: {cause}",
    "slow_end": "el destino #{n} vuelve a ir rápido",
    "poison_start": "el destino #{n} falla siempre con 1 de cada 20 eventos nuevos: {cause}",
    "poison_end": "los eventos nuevos vuelven a estar bien; los malos siguen fallando",
    "burst_start": "{times:.1f}x los eventos: {cause}",
    "burst_end": "se acabó el pico",
    "warn_lost": "{n} eventos abandonados",
    "warn_stuck": "{n} de {of} workers atascados en un destino",
    # el panel
    "tile_lost": "Perdidos",
    "tile_order": "Orden",
    "tile_p99": "p99",
    "bar_made": "Creados",
    "bar_sent": "Enviados",
    "bar_ended": "Acabados",
    "limit": "creados",
    "head_lost": "{n} eventos abandonados en 10 s",
    "head_stuck": "{n} de {of} workers atascados en #{endpoint}",
    "head_order": "{n} eventos entregados desordenados en 10 s",
    "head_down": "El destino #{n} está caído",
    "head_hang": "El destino #{n} no responde nunca",
    "head_slow": "El destino #{n} va lento",
    "head_poison": "El destino #{n} rechaza eventos mal formados",
    "head_burst": "Un pico de eventos",
    "head_ok": "Cada evento entregado, en orden",
    "stat_delivered": "entregados",
    "stat_lost": "perdidos",
    "stat_pending": "pendientes",
    "stat_order": "desordenados",
    "stat_busy": "workers",
    "title": "Webhooks",
    "subtitle": "por segundo, último 1 s",
    # los dibujos
    "state_down": "#{n} CAÍDO",
    "state_hang": "#{n} COLGADO",
    "state_slow": "#{n} LENTO",
    "state_poison": "#{n} VENENO",
    "state_burst": "PICO",
    "pic_state": "{state} · workers {busy}/{of}",
    "note": "Destinos: rojo muerto, naranja lento. Los puntos son una muestra (estético).",
}

LESSON = Lesson(
    title="Entrega de webhooks",
    one_liner="Entrega cada evento a cada cliente, en orden, sin que un destino roto tumbe a los demás.",
    learn=(
        "Un webhook es un POST de HTTP que mandas al servidor de un cliente cuando pasa algo (order.created, "
        "order.paid). Ese servidor no es tuyo: lo despliegan, su certificado caduca, su DNS cambia, su base "
        "de datos sufre. Así que la entrega es «al menos una vez»: guarda el evento, envíalo y consérvalo "
        "hasta recibir un 2xx. Enviar y olvidar pierde cada evento enviado mientras el destino está caído.",
        "Reintenta con backoff exponencial y jitter, y pon un timeout a cada intento. Sin timeout, un "
        "destino cuyas conexiones se cuelgan retiene cada worker lo que espere el cliente HTTP por defecto "
        "(30 s aquí, minutos en algunos clientes), y un grupo compartido de workers acaba entero atascado en "
        "un solo cliente.",
        "Los reintentos solos no bastan. Con una cola compartida, un destino muerto o lento se come los "
        "workers con sus timeouts y reintentos, y todos los demás clientes esperan (no hay aislamiento). Y "
        "los reintentos desordenan: order.paid sale bien mientras order.created espera su próximo "
        "reintento. Dale a cada destino su propia cola y un tope de workers (un mamparo), envía un evento "
        "por clave a la vez, el más viejo primero, y tras N fallos seguidos pausa el destino: pruébalo de "
        "vez en cuando y reenvía lo atrasado, en orden, cuando vuelva a responder. Un evento que falla solo "
        "mientras el destino funciona (uno mal formado) se abandona tras unos intentos, para que no bloquee "
        "su clave para siempre.",
        "Firma cada webhook: un HMAC-SHA256 de la marca de tiempo y el cuerpo con un secreto por destino, en "
        "una cabecera, para que el cliente compruebe que viene de ti y que no es una repetición (rechaza "
        "marcas de tiempo viejas). Y manda un id de evento: «al menos una vez» quiere decir que un POST que "
        "agotó su timeout puede haberse procesado, y el cliente debe ignorar el duplicado.",
    ),
    watch_for=(
        "Un solo envío: cuando el destino #1 se cuelga, cada worker acaba esperándolo (puntos naranjas "
        "junto al nodo rojo), los demás destinos se quedan sin servicio y sus eventos se pierden (morado).",
        "Reintentos: no se pierde nada, pero los timeouts y reintentos de #1 siguen llenando los workers, y "
        "cuando vuelve, los eventos de un mismo pedido llegan desordenados (naranja oscuro).",
        "Cola por destino: como mucho 4 workers esperan a #1, luego se pausa con una prueba cada 5 s; los "
        "demás destinos ni se enteran, y lo atrasado se reenvía en orden.",
    ),
    build=(
        ("Firma cada webhook (el esquema de Standard Webhooks)",
         "msg = f\"{event_id}.{timestamp}.{body}\"\n"
         "sig = base64.b64encode(hmac.new(secret, msg.encode(), hashlib.sha256).digest())\n"
         "headers = {\"webhook-id\": event_id, \"webhook-timestamp\": str(timestamp),\n"
         "           \"webhook-signature\": f\"v1,{sig.decode()}\"}"),
        ("Compruébalo al recibirlo, en tiempo constante",
         "expected = hmac.new(secret, msg.encode(), hashlib.sha256).digest()\n"
         "if abs(time.time() - timestamp) > 300 or not hmac.compare_digest(expected, received):\n"
         "    return 400  # falsificado o repetido"),
        ("Un timeout y un backoff con tope y jitter, con httpx",
         "client = httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=1.0))\n"
         "delay = random.uniform(0, min(30, 0.5 * 2 ** (attempt - 1)))  # jitter completo"),
    ),
    checklist=(
        "Guarda el evento antes de enviarlo; bórralo solo tras un 2xx.",
        "Pon un timeout a cada intento, de conexión y de lectura: unos pocos segundos como mucho.",
        "Reintenta con backoff exponencial y jitter completo, con tope, durante horas o días.",
        "Una cola por destino, con un tope de cuántos workers puede retener a la vez.",
        "Entrega en orden por clave de recurso: uno en vuelo por clave, el más viejo primero; o manda un "
        "número de secuencia y deja que el cliente pida el estado más reciente.",
        "Tras N fallos seguidos, desactiva (pausa) el destino, avisa al cliente, pruébalo y reenvía lo "
        "atrasado cuando esté sano.",
        "Firma cada webhook con un HMAC de la marca de tiempo y el cuerpo, y manda un id único de evento "
        "para descartar duplicados.",
        "Espera que los clientes respondan 2xx rápido y hagan el trabajo después; pon una alarma en la edad "
        "de lo atrasado de cada destino.",
    ),
    refs=(
        Ref("Standard Webhooks: the specification",
            "https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md",
            "Ids de evento, marcas de tiempo, firmas HMAC, reintentos: un esquema común para quien envía "
            "webhooks (en inglés)."),
        Ref("Stripe: Recibir eventos en tu webhook",
            "https://docs.stripe.com/webhooks?locale=es-419",
            "Reintentos durante días, destinos desactivados, firmas, y por qué el orden no está garantizado."),
        Ref("GitHub: Validating webhook deliveries",
            "https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries",
            "Cómo comprobar una firma HMAC-SHA256 en tiempo constante (en inglés)."),
        Ref("AWS Builders' Library: Timeouts, retries, and backoff with jitter",
            "https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/",
            "Por qué cada llamada necesita un timeout, y los reintentos backoff, jitter y un límite (en inglés)."),
        Ref("AWS Architecture Blog: Exponential Backoff And Jitter",
            "https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/",
            "Jitter completo, a medias y decorrelacionado, comparados (en inglés)."),
        Ref("AWS Builders' Library: Workload isolation using shuffle-sharding",
            "https://aws.amazon.com/builders-library/workload-isolation-using-shuffle-sharding/",
            "Por qué un cliente ruidoso no debe compartir todos los workers con los demás (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/webhook_delivery/es/main.py y mira cómo #1 se vuelve a colgar: no se pierde "
        "nada, pero los workers se siguen amontonando junto a él.",
        "Haz la etapa 2 y mira el mismo incidente: cuatro workers esperan a #1, luego se pausa y se prueba.",
        "Pon DISABLE_AFTER a 1000 (nunca pausar) y mira un cuelgue: #1 tiene a sus 4 workers esperando "
        "todo el rato, y el desperdicio pasa del 10%.",
    ),
)

"""Laboratorio hot_partition, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Partición caliente"
SUMMARY = "Un almacén repartido por clave en 6 particiones. Una clave explota: que ninguna se sature."
PARAMS = {"rate": "operaciones por segundo, tráfico normal"}

INCIDENT = IncidentText("Clave caliente", "la clave caliente", "la próxima clave caliente")
VERBS = {"viral": "VIRAL", "link": "CLICS", "sale": "OFERTA", "bot": "BOT", "calm": "CALMA"}
CAUSES = {
    "celebrity_post": "una famosa la compartió con 80 millones de seguidores",
    "viral_video": "un video que contiene se está haciendo viral",
    "live_vote": "un programa de televisión pide darle me gusta para votar",
    "breaking_news": "es la primera publicación sobre una noticia de última hora",
    "newsletter": "un boletín con 2 millones de lectores la enlaza",
    "push_notification": "una notificación se la mandó a todos los usuarios",
    "homepage": "la portada la destaca",
    "influencer": "una creadora de contenido la puso en su perfil",
    "flash_sale": "abre una oferta relámpago de un producto",
    "ticket_drop": "salen a la venta las entradas de una gira de estadios",
    "limited_sneaker": "a mediodía salen unas zapatillas de edición limitada",
    "price_glitch": "un error de precio corre por las redes sociales",
    "scraper": "un programa copia la página de un producto en bucle",
    "retry_loop": "una versión de la app móvil repite una petición en bucle",
    "health_check": "una comprobación de salud mal configurada lee un mismo id",
    "load_test": "alguien hace una prueba de carga en producción con un solo id",
}

STAGES = [
    StageText("Hash por clave",
              "Reto: una clave caliente satura su partición y las demás esperan. Reparte sus escrituras.",
              "Etapa 1: reparte las claves calientes en subclaves"),
    StageText("Claves repartidas",
              "Reto: las claves siguen repartidas para siempre: cada lectura suma todas sus subclaves.",
              "Etapa 2: reparte solo en caliente; caché de lecturas; reúne al enfriar"),
    StageText("Reparto adaptativo",
              "Resuelto: se reparte mientras está caliente, se lee de la caché y no se pierde nada.",
              "Todas las etapas hechas"),
]

GOALS = {
    "busiest": GoalText("Máxima < 90%", "reparte la clave caliente"),
    "throttled": GoalText("Rechazadas ≤ 1%", "reparte la clave caliente"),
    "p99": GoalText("p99 ≤ 100ms", "reparte; caché de lecturas"),
    "correct": GoalText("Perdidos = 0", "lee cada subclave; reúne"),
    "fanin": GoalText("Pet./op ≤ 1.1x", "reúne al enfriarse"),
}

LEGEND = {"cool": "bajo 50%", "busy": "cargada", "melting": "sobre 90%", "request": "petición",
          "hot_key": "clave caliente", "fan_in": "suma de subclaves", "cached": "de la caché",
          "throttled": "rechazada", "limit": "capacidad"}

STRINGS = {
    "fan_counters": "Contadores",
    "fan_part": "p{p} {util:.0%}",
    # incidentes
    "title_viral": "Publicación viral",
    "title_link": "Enlace viral",
    "title_sale": "Oferta relámpago",
    "title_bot": "Bot",
    "viral_start": "{key} en p{p}: ~{rate:.0f} me gusta/s, {cause}",
    "link_start": "{key} en p{p}: ~{rate:.0f} clics/s, {cause}",
    "sale_start": "{key} en p{p}: ~{rate:.0f} ventas y visitas/s, {cause}",
    "bot_start": "{key} en p{p}: ~{rate:.0f} lecturas/s, {cause}",
    "start_plain": "una clave recibe ~{rate:.0f} operaciones/s: {cause}",
    "end": "{key} se enfría",
    "end_plain": "la clave se enfría",
    "warn_throttled": "{n} operaciones rechazadas",
    # el panel
    "tile_busiest": "Máxima",
    "tile_throttled": "Rechaz.",
    "tile_p99": "p99",
    "title": "Particiones",
    "subtitle": "peticiones/s, último 1 s",
    "limit": "capacidad {limit:.0f}/s",
    "chart_limit": "capacidad {limit:.0f}/s",
    "head_refused": "p{p} rechaza {n} peticiones por segundo",
    "head_spread": "{key} en {n} particiones",
    "head_one": "{key} está caliente, toda en p{p}",
    "head_ok": "La partición más cargada está al {util:.0%}",
    "note_nodes": "Nodos: p0-p5, color según su carga.",
    "note_chart": "Gráfica: peticiones/s a la más cargada.",
    # los dibujos
    "state_melting": "p{p} SATURADA {util:.0%}",
    "state_spread": "CLAVE CALIENTE EN {n} PARTICIONES, máxima {util:.0%}",
    "state_ok": "EQUILIBRADO, máxima {util:.0%}",
    # el dibujo de carriles: estados bajo el servidor, 13 letras como mucho
    "lanes_melting": "p{p} AL {util:.0%}",
    "lanes_spread": "EN {n} PARTES",
    "lanes_ok": "MÁXIMA {util:.0%}",
    # errores en tu código
    "stuck": "un incr() o read() lleva más de {seconds:.0f} s en marcha: ¿vuelve cada await?",
}

LESSON = Lesson(
    title="Particiones calientes",
    one_liner="El hash reparte claves, no tráfico: una clave que explota satura su partición. Divídela, "
              "guárdala en caché y vuelve a juntarla.",
    learn=(
        "Un almacén repartido por hash(clave) pone cada clave en una partición. Así las claves quedan "
        "repartidas por igual, y con muchas claves de popularidad modesta la carga también. Pero todo el "
        "tráfico de una clave cae siempre en la misma partición: cuando una publicación se hace viral o un "
        "bot machaca un id, esa partición rechaza peticiones y da timeouts mientras las otras cinco están ociosas. "
        "Añadir particiones no ayuda: la clave sigue en una de ellas.",
        "Repartir las escrituras (salting) divide un contador caliente en N subclaves, clave#1 ... clave#N, puestas en "
        "particiones distintas. Cada incremento va a una subclave al azar, así que las escrituras se reparten "
        "N veces. Una lectura ahora tiene que leer cada subclave y sumarlas. Si se olvida una, se pierden "
        "incrementos.",
        "Repartir no sale gratis. Cada lectura de una clave repartida cuesta N peticiones, así que repartir "
        "una clave muy leída, o dejarla repartida cuando se enfría, multiplica la carga en vez de repartirla. "
        "Reparte solo mientras la clave está caliente de escrituras, elige N según el calor, y cuando se "
        "enfríe vuelve a juntar las subclaves en la clave (deja de escribir en ellas, espera a las escrituras "
        "en vuelo y mueve sus cuentas).",
        "Las lecturas calientes piden otro remedio: una caché pequeña delante del almacén, solo para claves "
        "calientes, con un TTL corto. Una cuenta de medio segundo de antigüedad sirve para un contador de me "
        "gusta, y la partición pasa de cuatrocientas lecturas por segundo a dos.",
    ),
    watch_for=(
        "Hash por clave: un nodo se pone rojo, le llueven puntos morados y los rojos mueren a medio camino; "
        "los demás siguen azules.",
        "Repartidas: los puntos morados se reparten por los seis nodos, pero cada lectura manda ahora seis "
        "puntos naranjas, y cuando la clave se enfría el naranja sigue (Pet./op).",
        "Adaptativo: la clave se reparte solo mientras está caliente, las lecturas de un bot salen de la caché "
        "(azul en la puerta) y, al enfriarse, el naranja se acaba.",
        "Incrementos perdidos: el almacén debe guardar justo lo confirmado al cliente. Se comprueba cada "
        "medio segundo.",
    ),
    build=(
        ("DynamoDB: repartir las escrituras de un contador caliente (boto3)",
         "shard = random.randrange(N)\n"
         "table.update_item(Key={\"pk\": f\"{key}#{shard}\"},\n"
         "                  UpdateExpression=\"ADD likes :one\",\n"
         "                  ExpressionAttributeValues={\":one\": 1})\n"
         "# lectura: BatchGetItem de cada f\"{key}#{i}\" para i en range(N), y súmalos"),
        ("Detectar una clave caliente: cuenta las operaciones por clave del último cuarto de segundo",
         "times = recent.setdefault(key, deque())\n"
         "times.append(now)\n"
         "while times[0] <= now - 0.25:\n"
         "    times.popleft()\n"
         "rate = len(times) / 0.25  # operaciones por segundo"),
        ("Volver a juntar una clave que se enfrió",
         "writing[key] = 1                 # las escrituras nuevas van a la propia clave\n"
         "await asyncio.sleep(GRACE)       # aterrizan las escrituras en vuelo a una subclave\n"
         "for i in range(1, width[key]):\n"
         "    await store.incr(key, await store.take(f\"{key}#{i}\"))\n"
         "width[key] = 1                   # las lecturas dejan de sumar subclaves"),
    ),
    checklist=(
        "Mira la carga de cada partición, no la media: la media esconde una partición saturada.",
        "Encuentra las claves calientes al momento, con cuentas recientes por clave (una ventana deslizante).",
        "Reparte las claves calientes de escrituras en N subclaves en particiones distintas; N según el calor.",
        "Cada lectura de una clave repartida lee cada subclave en la que pudo escribir; cambiar N no debe "
        "esconder ninguna.",
        "Guarda en caché las claves calientes de lecturas con un TTL corto, cerca de los clientes; no las repartas.",
        "Vuelve a juntar las subclaves cuando la clave se enfríe, después de que aterricen las escrituras en vuelo.",
        "Comprueba las sumas: lo que guarda el almacén debe ser igual a lo confirmado al cliente.",
    ),
    refs=(
        Ref("Amazon DynamoDB: Using write sharding to distribute workloads evenly",
            "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-sharding.html",
            "Sufijos aleatorios y calculados en una clave de partición caliente."),
        Ref("Amazon DynamoDB: Burst and adaptive capacity",
            "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/burst-adaptive-capacity.html",
            "Cómo DynamoDB aísla un elemento caliente en su propia partición, y dónde deja de bastar."),
        Ref("Discord: How Discord stores trillions of messages",
            "https://discord.com/blog/how-discord-stores-trillions-of-messages",
            "Particiones calientes en Cassandra y ScyllaDB, y peticiones agrupadas delante de ellas."),
        Ref("Scaling Memcache at Facebook (NSDI 2013)",
            "https://www.usenix.org/system/files/conference/nsdi13/nsdi13-final170_update.pdf",
            "Claves calientes, cómo evitar estampidas y cómo replicar las claves populares."),
        Ref("Cloud Bigtable: Schema design",
            "https://cloud.google.com/bigtable/docs/schema-design",
            "Claves de fila que reparten las escrituras, y las que las amontonan en un nodo."),
        Ref("Apache HBase reference guide: Rowkey design",
            "https://hbase.apache.org/book.html#rowkey.design",
            "Puntos calientes, prefijos y hash en las claves de fila."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/hot_partition/es/main.py y mira cómo la próxima publicación viral se reparte "
        "en seis particiones.",
        "Espera a un bot: repartir no ayuda a las lecturas. Haz la etapa 2 y mira cómo las absorbe la caché.",
        "Prueba --set rate=250: el tráfico normal deja menos sitio, y N importa más.",
    ),
)

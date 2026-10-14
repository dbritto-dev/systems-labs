"""Laboratorio kafka_log, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Log de Kafka (Gossip Glomers #5)"
SUMMARY = "Gossip Glomers #5: un log estilo Kafka replicado en dos nodos; primero correcto, luego barato."
PARAMS = {"rate": "operaciones de clientes por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"burst": "PICO", "calm": "CALMA", "slow": "LENTO", "fast": "RÁPIDO"}
CAUSES = {
    "replay": "un productor reenvió un día entero de eventos a un solo topic",
    "flash_sale": "una venta relámpago mandó todos los pedidos a un solo topic",
    "retry_storm": "una tormenta de reintentos aguas arriba machacó un topic",
    "compaction": "lin-kv está compactando su almacenamiento",
    "noisy_disk": "un vecino ruidoso acapara el disco de lin-kv",
    "lost_replica": "lin-kv perdió una réplica y se está poniendo al día",
}

STAGES = [
    StageText("Un solo nodo",
              "Reto: cada nodo reparte sus propios offsets y dos mensajes comparten uno. Que coincidan.",
              "Etapa 1 (5b): guarda offsets y mensajes en lin-kv"),
    StageText("Multinodo",
              "Reto: es correcto, pero cada send cuesta ~10 mensajes y se atasca en una clave caliente.",
              "Etapa 2 (5c): menos viajes, p. ej. un dueño por clave"),
    StageText("Eficiente",
              "Resuelto: offsets únicos, nada se pierde, y un send cuesta más o menos un mensaje.",
              "Todas las etapas hechas"),
]

GOALS = {
    "unique": GoalText("Offsets únicos", "pon de acuerdo los offsets"),
    "lost_writes": GoalText("Nada perdido", "no saltes ningún offset"),
    "commits": GoalText("Commits guardados", "comparte los commits"),
    "msgs": GoalText("Msgs/op < 3", "menos viajes a lin-kv"),
    "p99": GoalText("p99 send < 100ms", "un dueño por clave"),
}

LEGEND = {"node": "nodo", "lin_kv": "lin-kv", "anomaly": "anomalía", "client_request": "petición de cliente",
          "node_message": "mensaje entre nodos", "kv_message": "mensaje a lin-kv", "limit": "límite"}

STRINGS = {
    # incidentes
    "title_burst": "Clave caliente",
    "title_slowkv": "lin-kv lento",
    "burst_start": "{severity:.1f}x de tráfico, casi todo sends a una clave: {cause}",
    "burst_end": "el tráfico vuelve a la normalidad",
    "slow_start": "lin-kv responde {severity:.0f}x más lento: {cause}",
    "slow_end": "lin-kv vuelve a ser rápido",
    "warn_slow": "los sends tardan más de 300 ms",
    "one_key": "una clave",
    # anomalías
    "duplicate": "offset duplicado",
    "lost_write": "escritura perdida",
    "lost_commit": "commit perdido",
    # valores de los objetivos
    "failed": "falló",
    # el panel
    "tile_msgs": "Msgs/op",
    "tile_p99": "p99",
    "tile_anomalies": "Anomalías",
    "traffic": "Tráfico",
    "bar_clients": "Clientes",
    "bar_messages": "Mensajes",
    "limit": "{limit:.0f} msgs/op",
    "chart_limit": "{limit:.0f}/op",
    "head_anomaly": "¡{what} en {k}!",
    "head_hot": "{k} caliente: p99 send {p99}",
    "head_slow": "lin-kv va lento: p99 send {p99}",
    "head_ok": "Log bien: {mpo} mensajes por operación",
    "note_dots": "Puntos más lentos para que se vean (estético).",
    # el dibujo
    "state_hot": "CLAVE CALIENTE {k}",
    "state_kv_slow": "LIN-KV LENTO",
    # el dibujo de carriles (lo que ven los clientes): estados bajo el clúster, 13 letras como mucho
    "lanes_anomaly": "ANOMALÍA",
    "lanes_kv_slow": "KV LENTO",
}

LESSON = Lesson(
    title="Log de Kafka (Gossip Glomers #5)",
    one_liner="Un log replicado de solo añadir: cada mensaje recibe un offset único y ningún lector se salta uno.",
    learn=(
        "Un log por clave: cada mensaje recibe un offset, los offsets solo crecen, y los lectores "
        "(consumidores) hacen poll desde un offset y hacen commit de hasta dónde llegaron. Kafka, Redpanda "
        "y Pulsar funcionan así.",
        "Con dos nodos, si cada uno cuenta offsets por su cuenta, reparte el mismo offset a dos mensajes "
        "distintos, y un lector en un nodo nunca ve los mensajes del otro.",
        "Un almacén linealizable (lin-kv) arregla la corrección: un contador por clave que se sube con "
        "compare-and-swap da offsets únicos. Pero ahora cada send cuesta varios viajes de ida y vuelta, y "
        "los sends concurrentes a una clave caliente se pelean por el contador: fallos de CAS, reintentos "
        "y una latencia que se dispara.",
        "Repartir la propiedad quita la contención: un nodo es dueño de cada clave y asigna sus offsets en "
        "memoria; el otro nodo le reenvía las peticiones. Un mensaje por operación, sin viajes al "
        "almacenamiento. Así funciona el propio Kafka (un líder por partición).",
    ),
    watch_for=(
        "Un solo nodo: destellos rojos y OFFSET DUPLICADO / ESCRITURA PERDIDA bajo los nodos.",
        "Multinodo: sin anomalías, pero mensajes naranjas a lin-kv por todas partes; en un pico el p99 del "
        "send se dispara.",
        "Eficiente: pocos mensajes azules entre los nodos, y los sends siguen rápidos durante los picos.",
        "Que lin-kv se vuelva lento perjudica a cualquier diseño que lo espere en el camino crítico.",
    ),
    build=(
        ("Maelstrom: ejecuta el reto real contra tu propio binario",
         "./maelstrom test -w kafka --bin ./my-kafka --node-count 2 \\\n"
         "    --concurrency 2n --time-limit 20 --rate 1000"),
        ("Kafka: el dueño de una partición es su líder",
         "kafka-topics --create --topic orders --partitions 12 --replication-factor 3\n"
         "# cada partición tiene un broker líder que asigna los offsets; los productores le envían a él"),
    ),
    checklist=(
        "Decide quién asigna el orden: un dueño (líder) por clave gana a un contador compartido con contención.",
        "Nunca confirmes un offset antes de guardar el mensaje donde los lectores lo vayan a encontrar.",
        "Un poll puede devolver menos mensajes, nunca un hueco por debajo de lo que devuelve.",
        "Los offsets confirmados solo avanzan; guárdalos donde cualquier nodo pueda leerlos.",
        "Cuenta los viajes de ida y vuelta en el camino crítico, y prueba con una clave caliente.",
    ),
    refs=(
        Ref("Fly.io: Gossip Glomers #5a Single-Node Kafka-Style Log", "https://fly.io/dist-sys/5a/",
            "El reto original (en inglés)."),
        Ref("Fly.io: #5b Multi-Node Kafka-Style Log", "https://fly.io/dist-sys/5b/",
            "Dos nodos y lin-kv: primero la corrección (en inglés)."),
        Ref("Fly.io: #5c Efficient Kafka-Style Log", "https://fly.io/dist-sys/5c/",
            "Menos fallos de CAS y menos mensajes por operación (en inglés)."),
        Ref("Maelstrom: the kafka workload", "https://github.com/jepsen-io/maelstrom/blob/main/doc/workloads.md",
            "Los mensajes y las anomalías que busca su comprobador (en inglés)."),
        Ref("Apache Kafka: design", "https://kafka.apache.org/documentation/#design",
            "Particiones, líderes, offsets y posiciones de los consumidores (en inglés)."),
        Ref("Jepsen: Redpanda 21.10.1", "https://jepsen.io/analyses/redpanda-21.10.1",
            "Escrituras perdidas y duplicadas reales en un log compatible con Kafka, y cómo se encontraron "
            "(en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/kafka_log/es/main.py con lin-kv y mira cómo paran las anomalías.",
        "Luego mira un pico en una clave caliente: ¿cuántos reintentos de CAS cuesta un send?",
        "Prueba --set rate=60: ¿tu diseño de la etapa 2 sigue costando más o menos un mensaje por operación?",
    ),
)

"""Laboratorio chain_replication, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Replicación en cadena"
SUMMARY = "Un almacén clave/valor en una cadena de 4 nodos. Nunca leas datos viejos ni pierdas una escritura confirmada."
PARAMS = {"rate": "operaciones de clientes por segundo (mitad escrituras, mitad lecturas)"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"crash": "CAÍDA", "slow": "LENTO", "join": "ENTRA"}
CAUSES = {
    "kernel_panic": "un kernel panic tras actualizar un driver",
    "bad_deploy": "un despliegue malo lo tumbó al arrancar",
    "host_reboot": "su máquina se reinició por un parche del kernel",
    "oom_kill": "el kernel lo mató por usar demasiada memoria",
    "disk_failure": "se rompió su disco",
    "power_supply": "falló una fuente de alimentación de su rack",
    "gc_pause": "pausas largas del recolector de basura",
    "disk_full": "su disco está casi lleno y cada escritura se arrastra",
    "noisy_neighbour": "un vecino ruidoso le roba la CPU",
}

STAGES = [
    StageText("Primario-respaldo",
              "Reto: las lecturas de los respaldos no ven escrituras confirmadas. Haz una cadena.",
              "Etapa 1: escrituras de la cabeza a la cola, la cola confirma; lee de la cola"),
    StageText("Cadena",
              "Reto: un nodo caído atasca la cadena para siempre. Repárala.",
              "Etapa 2: con una cadena nueva, reenvía lo enviado y no confirmado"),
    StageText("Cadena + reparación",
              "Resuelto: ni lecturas viejas ni escrituras perdidas, y la cadena se cura en un segundo.",
              "Todas las etapas hechas"),
]

GOALS = {
    "stale": GoalText("Lect. viejas = 0", "lee de la cola"),
    "lost": GoalText("Escr. perdidas = 0", "que confirme la cola"),
    "outage": GoalText("Sin escribir ≤ 3s", "reenvía lo no confirmado"),
    "replicas": GoalText("Al día = 4", "la cola guarda tras la copia"),
    "p99": GoalText("Escr. p99 ≤ 500ms", "no esperes a cada escritura"),
}

LEGEND = {"request": "petición de cliente", "write": "escritura", "ack": "confirmación", "copy": "copia",
          "in_sync": "al día", "behind": "atrasado", "slow": "lento", "down": "caído / fuera",
          "limit": "escrituras", "incident": "incidente"}

STRINGS = {
    # incidentes
    "head_start": "{node}, la cabeza, se cayó: {cause}",
    "middle_start": "{node}, en medio de la cadena, se cayó: {cause}",
    "tail_start": "{node}, la cola, se cayó: {cause}",
    "slow_start": "{node} va lento y atasca la cadena: {cause}",
    "back": "{node} vuelve, vacío: copia el estado de la cola y entra como cola",
    "warn_dropped": "el maestro saca a {node} de la cadena",
    "warn_ejected": "el maestro expulsa a {node}; arranca de nuevo vacío",
    "warn_lost": "{n} escrituras confirmadas perdidas",
    "warn_stale_after": "{n} lecturas viejas después de que entrara {node}",
    # valores de los objetivos
    "seconds": "{n} s",
    # el panel
    "title": "Escrituras y lecturas",
    "tile_stale": "Viejas",
    "tile_lost": "Perdidas",
    "tile_writes": "Escr.",
    "bar_writes": "Escritas",
    "bar_reads": "Lecturas",
    "limit": "escrituras",
    "head_chain": "Cadena {chain}",
    "note_chart": "Gráfica: escrituras por segundo: rápidas, lentas (más de 0.5 s), fallidas.",
    # lo que vive la cadena: una frase (clúster, titular) ...
    "sit_lost": "escrituras confirmadas perdidas",
    "sit_stale": "lecturas que no ven escrituras confirmadas",
    "sit_down": "{node} caído: el maestro lo nota en 1 s",
    "sit_slow": "{node} lento: la cadena se atasca",
    "sit_stalled": "{n} escrituras atascadas",
    "sit_copying": "{node} copia el estado de la cola",
    "sit_short": "{n} de {of} réplicas",
    # ... y una o dos palabras bajo el servidor del dibujo de carriles, 13 letras como mucho
    "short_lost": "PERDIDAS",
    "short_stale": "DATOS VIEJOS",
    "short_down": "{node} CAÍDO",
    "short_slow": "{node} LENTO",
    "short_stalled": "ATASCADA",
    "short_copying": "{node} COPIA",
    "short_short": "{n}/{of} RÉPLICAS",
    # el dibujo del clúster: una palabra bajo cada nodo
    "role": "{node} {role}",
    "role_head": "cabeza",
    "role_tail": "cola",
    "role_down": "caído",
    "role_copying": "copia",
    "role_out": "fuera",
    # errores en tu código
    "no_store": "ChainNode debe guardar sus datos en self.store",
    "bad_read_from": "read_from devolvió {node!r}: debe devolver un nodo de la cadena",
}

LESSON = Lesson(
    title="Replicación en cadena",
    one_liner="Pon las réplicas en fila: las escrituras entran por la cabeza y salen por la cola; lee de la cola.",
    learn=(
        "Primario-respaldo con replicación asíncrona responde a una escritura antes de que la tengan los "
        "respaldos. Una lectura de un respaldo puede no verla (una lectura vieja), y si el primario se "
        "cae antes, se pierde una escritura que al cliente se le dijo que estaba a salvo.",
        "La replicación en cadena (van Renesse y Schneider, 2004) pone las réplicas en fila. La cabeza "
        "numera cada escritura y la pasa; cada nodo la aplica en orden y la pasa; la cola la aplica la "
        "última y responde al cliente. Las lecturas van a la cola: cada escritura que tiene está en "
        "todas las réplicas, así que una lectura nunca ve una escritura que se pueda perder, ni deja de "
        "ver una confirmada. Es consistencia fuerte con un solo nodo respondiendo lecturas.",
        "Un maestro de configuración (ZooKeeper, etcd, Chubby) decide quién está en la cadena. Cuando "
        "un nodo se cae, lo saca: el siguiente pasa a ser la cabeza, o el predecesor pasa a ser la cola, "
        "o el predecesor de un nodo caído en medio reenvía lo que envió y nunca vio confirmado.",
        "Cada nodo guarda las escrituras que pasó hasta que la confirmación de la cola sube de vuelta "
        "(la lista Sent del artículo). Esa lista hace posible cada reparación, y también que entre un "
        "nodo nuevo: copia el estado de la cola, la cola guarda lo que aplica mientras tanto y se lo "
        "reenvía cuando el nodo nuevo es su sucesor.",
        "Cada escritura cruza todos los nodos, así que la latencia de la cadena es la suma de los saltos, "
        "y un nodo lento frena todas las escrituras: el maestro debe expulsar a un nodo lento, no solo a "
        "uno caído.",
    ),
    watch_for=(
        "Primario-respaldo: la tarjeta Viejas se pone roja sin que nada falle; si cae la cabeza, Perdidas también.",
        "Una cadena: nada viejo, nada perdido; pero cuando cae n1 las escrituras se atascan para siempre (Escr. en 0%).",
        "Reparar sin guardar escrituras durante la copia: el nodo que entra se pierde algunas y la cadena se atasca.",
        "Cadena + reparación: una caída cuesta como mucho un segundo de escrituras; la copia (naranja) vuela a la cola nueva.",
    ),
    build=(
        ("La lista Sent del artículo, en cada nodo menos la cola",
         "sent[seq] = write; send(successor, write)    # al pasarla\n"
         "del sent[s] for s <= ack.seq                 # la cola ya la tiene\n"
         "con un sucesor nuevo: reenvía sent           # descarta lo que ya tiene"),
        ("Una cadena en ZooKeeper: un znode efímero y secuencial por réplica",
         "create -e -s /chain/node- n3:7000    # el orden es la cadena; una sesión caída lo borra"),
        ("Aplica en orden, lleguen como lleguen los mensajes",
         "pending[w.seq] = w\n"
         "while self.seq + 1 in pending:\n"
         "    self.apply(pending.pop(self.seq + 1))"),
    ),
    checklist=(
        "Lee de la cola (o pregunta a la cola qué versión está consolidada antes de leer en otro nodo).",
        "Numera las escrituras en la cabeza y aplícalas en ese orden en cada réplica.",
        "Guarda lo enviado y no confirmado hasta que vuelva la confirmación de la cola; reenvíalo tras una reparación.",
        "Deja la pertenencia a un maestro fiable (ZooKeeper, etcd), con timeouts de sesión para los nodos caídos.",
        "Expulsa también a los nodos lentos: una réplica lenta frena cada escritura de la cadena.",
        "Añade un nodo a la cola solo cuando haya copiado el estado y la cola le haya reenviado lo que vino después.",
    ),
    refs=(
        Ref("van Renesse and Schneider: Chain Replication (OSDI 2004)",
            "https://www.usenix.org/legacy/event/osdi04/tech/full_papers/renesse/renesse.pdf",
            "El artículo original: el protocolo, el maestro y cada reparación (en inglés)."),
        Ref("Terrace and Freedman: Object Storage on CRAQ (USENIX ATC 2009)",
            "https://www.usenix.org/legacy/event/usenix09/tech/full_papers/terrace/terrace.pdf",
            "Replicación en cadena con lecturas desde cualquier nodo, y aún consistencia fuerte (en inglés)."),
        Ref("Apache ZooKeeper: recipes",
            "https://zookeeper.apache.org/doc/current/recipes.html",
            "Znodes efímeros y secuenciales: cómo un maestro fiable guarda los miembros y su orden (en inglés)."),
        Ref("Jepsen: consistency models",
            "https://jepsen.io/consistency",
            "Qué significa exactamente «nunca leer datos viejos» (linealizabilidad) (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/chain_replication/es/main.py y mira cómo la tarjeta Viejas se queda en cero.",
        "Luego espera a las 0:20: ¿qué les pasa a las escrituras cuando cae n1?",
        "Haz la etapa 2 y mira cómo el predecesor reenvía, y cómo la copia vuela al nodo que entra.",
    ),
)

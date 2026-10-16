"""Laboratorio merkle_anti_entropy, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Antientropía con árboles de Merkle"
SUMMARY = "4 réplicas de 20.000 claves se separan sin avisar: halla y repara las diferencias, barato."
PARAMS = {"rate": "escrituras de clientes por segundo (las lecturas son el doble)"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"down": "CAÍDA", "up": "VUELVE", "blip": "CORTE", "heal": "UNIDA", "disk": "DISCO", "restore": "COPIA"}
CAUSES = {
    "kernel_panic": "un pánico del kernel tras actualizar un controlador",
    "oom_kill": "el sistema mató el proceso de la base de datos por falta de memoria",
    "host_reboot": "reiniciaron su máquina para un parche de seguridad",
    "switch_failover": "un switch de rack pasó al de respaldo",
    "nic_reset": "su tarjeta de red se reinició con la carga",
    "conntrack": "se llenó la tabla de conexiones del cortafuegos",
    "bit_rot": "datos degradados: fallaron las sumas de control y se descartaron las claves",
    "bad_sector": "sectores dañados en un disco viejo",
    "raid_rebuild": "una reconstrucción del RAID perdió una franja",
    "wrong_snapshot": "se restauró la instantánea equivocada tras una migración",
    "operator_error": "un operador restauró por error la copia de la semana pasada",
    "rollback": "un proceso de vuelta atrás restauró un archivo de datos viejo",
}

STAGES = [
    StageText("Sin reparación",
              "Reto: las escrituras perdidas nunca se reparan; cada réplica responde distinto. Repara.",
              "Etapa 1: un barrido completo: compara cada clave con un par"),
    StageText("Barrido completo",
              "Reto: convergen, pero cada ronda envía las 20.000 claves. Envía solo lo que difiere.",
              "Etapa 2: árboles de Merkle: baja donde difieren los hash"),
    StageText("Árboles de Merkle",
              "Resuelto: los hash hallan las diferencias y se reparan en segundos, con pocas entradas.",
              "Todas las etapas hechas"),
]

GOALS = {
    "fixed": GoalText("Al día ≤ 15 s", "rondas de antientropía"),
    "stale": GoalText("Viejas ≤ 0.2%", "repara cada clave a tiempo"),
    "sent": GoalText("Envío ≤ 150", "Merkle con hojas pequeñas"),
    "hashes": GoalText("Hash ≤ 10k/s", "árbol al día en cada cambio"),
}

LEGEND = {"in_sync": "al día", "diverged": "le faltan escrituras", "down": "caída", "request": "petición de cliente",
          "replication": "replicación", "repair": "reparación", "dropped": "perdido"}

STRINGS = {
    # objetivos
    "left": "aún {n:,}",
    "per_key": "{v:.0f}/clave",
    "none_fixed": "{n:,} por 0",
    "rate": "{v:,.0f}/s",
    # incidentes
    "down": "{node} está caído: {cause}; los demás guardan {hints} pistas cada uno para él",
    "up": "{node} vuelve; se reenvían las pistas",
    "blip": "un corte de red aisló a {node}: {cause}; se pierden lotes de replicación",
    "healed": "{node} vuelve a estar accesible",
    "disk": "un disco dañado perdió {n:,} claves en {node}: {cause}",
    "restore": "una copia vieja de {first}…{last} ({n:,} claves) vuelve a {node}: {cause}",
    "warn_hints": "{n:,} escrituras para {node} no cupieron en sus pistas: nunca se enviaron",
    "warn_diverged": "{n:,} claves difieren tras el incidente",
    # el panel
    "tile_diverged": "Difieren",
    "tile_stale": "Viejas",
    "tile_sent": "Envío",
    "limit": "10k/s",
    "hash_title": "Cálculo de hash",
    "hash_sub": "por réplica, 1 s",
    "head_down": "{node} caído: se acumulan pistas",
    "head_blip": "{node} aislado: lotes perdidos",
    "head_diverged": "{n:,} claves difieren, más en {node}",
    "head_repaired": "{n:,} claves reparadas en 1 s",
    "head_ok": "Cada réplica tiene lo último",
    "stat_reads": "lecturas",
    "stat_writes": "escrituras",
    "stat_stale": "viejas",
    "stat_diverged": "difieren",
    "stat_repair": "reparación",
    "note_chart": "Gráfica: entradas enviadas por segundo: replicación, reparación.",
    # el dibujo
    "state_down": "{node} CAÍDO",
    "state_diverged": "DIFIEREN {n:,}",
    "state_sync": "AL DÍA",
    # el dibujo de carriles (lo que ven los clientes): estados bajo el servidor, 13 letras como mucho
    "lanes_stale": "LEEN VIEJO",
    "lanes_diverged": "DIFIEREN",
    "lanes_sync": "AL DÍA",
    # el dibujo de pares: bajo cada réplica, lo que le falta, corto
    "peer_down": "{node} caído",
    "peer_cut": "{node} aislado",
    "peer_missing": "{node} −{n}",
    # errores en tu código
    "not_replica": "ReplicaNode debe heredar de Replica (de labs.merkle_anti_entropy.api)",
}

LESSON = Lesson(
    title="Antientropía con árboles de Merkle",
    one_liner="Las réplicas se separan sin avisar; compara árboles de hash para hallar las pocas claves que "
              "difieren, no todas.",
    learn=(
        "La replicación pierde escrituras de vez en cuando, y nadie te avisa: una réplica caída más "
        "tiempo del que cubren sus pistas, un corte de red que pierde un lote, un disco dañado, una "
        "copia vieja restaurada por error. Sin reparación esas réplicas se quedan mal para siempre, y "
        "cada lectura depende de qué réplica responde.",
        "La antientropía es un proceso de fondo que compara réplicas y copia la versión más nueva de "
        "cada clave que difiere. La más simple, un barrido completo, envía a un par la versión de cada "
        "clave: lo repara todo, pero su costo crece con los datos, no con las diferencias.",
        "Un árbol de Merkle resume con hash el rango de claves: cada hoja cubre unas pocas claves, cada "
        "nodo interior es el hash de sus hijos, y la raíz lo resume todo. Dos réplicas comparan raíces; "
        "si difieren, comparan los hijos y bajan solo donde los hash difieren, y luego intercambian las "
        "claves de las hojas que difieren (Dynamo, Cassandra, Riak).",
        "Mantén el árbol al día en cada escritura (unos pocos hash por un camino), en vez de "
        "reconstruirlo con todos los datos en cada ronda. Elige el tamaño de hoja: hojas grandes envían "
        "muchas claves buenas con cada clave mala; hojas diminutas hacen un árbol hondo con más hash "
        "que intercambiar.",
    ),
    watch_for=(
        "Sin reparación: tras un incidente una réplica sigue naranja para siempre, y algunas lecturas "
        "dan versiones viejas.",
        "Barrido completo: las réplicas vuelven a azul, pero la gráfica es un muro de reparación en cada ronda.",
        "Árboles de Merkle: una ronda en calma cuesta unos cientos de entradas; tras un incidente, una "
        "ráfaga corta lo repara.",
        "Hojas demasiado grandes, o un árbol reconstruido en cada ronda: Envío o el cálculo de hash "
        "pasa su límite.",
    ),
    build=(
        ("Cassandra: repara una tabla (árboles de Merkle por rango de tokens)",
         "nodetool repair --full my_keyspace my_table\n"
         "nodetool repair -pr my_keyspace          # solo los rangos primarios de este nodo"),
        ("Riak: antientropía activa, árboles de hash al día en cada escritura",
         "riak.conf:\n"
         "  anti_entropy = active\n"
         "  anti_entropy.tree.build_limit.per_timespan = 1h"),
        ("Bajar por un árbol de Merkle: solo los hijos cuyo hash difiere",
         "nodes = [root]\n"
         "while level < depth:\n"
         "    differ = await peer.compare(level, {i: tree.hash(level, i) for i in nodes})\n"
         "    nodes = [c for i in differ for c in tree.children(i)]"),
    ),
    checklist=(
        "Da por hecho que las réplicas se separan: ejecuta la antientropía siempre, no solo tras "
        "incidentes conocidos.",
        "Haz que su costo crezca con las diferencias, no con los datos: compara hash primero.",
        "Mantén los árboles incrementales, y limita la reparación para que no dañe el tráfico normal.",
        "Elige hojas de unas pocas claves a unos cientos, para que una clave mala no arrastre un rango entero.",
        "Alerta por volumen de reparación: una ráfaga repentina significa que algo perdió escrituras.",
    ),
    refs=(
        Ref("Amazon Dynamo (SOSP 2007)",
            "https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf",
            "Secciones 4.6 y 4.7: pistas para réplicas caídas, y sincronizar réplicas con árboles de "
            "Merkle (en inglés)."),
        Ref("Apache Cassandra: repair",
            "https://cassandra.apache.org/doc/latest/cassandra/managing/operating/repair.html",
            "Reparación completa e incremental, y cómo se construyen y comparan los árboles (en inglés)."),
        Ref("Apache Cassandra: hints",
            "https://cassandra.apache.org/doc/latest/cassandra/managing/operating/hints.html",
            "Las pistas, su ventana, y por qué hace falta reparar igualmente (en inglés)."),
        Ref("Riak KV: active anti-entropy",
            "https://docs.riak.com/riak/kv/latest/learn/concepts/active-anti-entropy/index.html",
            "Árboles de hash al día en tiempo real, comparados sin parar entre réplicas (en inglés)."),
        Ref("ScyllaDB: row-level repair",
            "https://www.scylladb.com/2019/08/13/scylla-open-source-3-1-efficiently-maintaining-consistency-with-row-level-repair/",
            "Por qué hojas de Merkle grandes envían muchos más datos que las diferencias, y un arreglo "
            "(en inglés)."),
        Ref("Van Renesse et al.: efficient reconciliation for anti-entropy",
            "https://www.cs.cornell.edu/home/rvr/papers/flowgossip.pdf",
            "Protocolos de antientropía, qué envían y cómo acotarlo (en inglés)."),
        Ref("Árbol de Merkle (Wikipedia)",
            "https://es.wikipedia.org/wiki/%C3%81rbol_de_Merkle",
            "Árboles de hash: la idea, y dónde más se usan."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/merkle_anti_entropy/es/main.py y mira cómo las réplicas vuelven a azul, "
        "y la gráfica.",
        "Luego compara lo que envía un barrido completo con las claves que repara (Envío).",
        "Haz la etapa 2; luego prueba DEPTH = 1 y DEPTH = 4 y mira cómo se mueven Envío y el "
        "cálculo de hash.",
    ),
)

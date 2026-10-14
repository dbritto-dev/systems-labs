"""Laboratorio quorum, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Quórums"
SUMMARY = "Replicación al estilo Dynamo: cada clave en 3 de 5 nodos. Lee la última escritura con un nodo caído."
PARAMS = {"rate": "operaciones de clientes por segundo (mitad put, mitad get)"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"crash": "CAÍDA", "cut": "CORTE", "slow": "LENTO", "back": "VUELVE", "fast": "RÁPIDO"}
CAUSES = {
    "oom_kill": "el kernel lo mató por usar demasiada memoria",
    "kernel_panic": "un kernel panic tras actualizar un driver",
    "bad_deploy": "un despliegue malo lo tumbó al arrancar",
    "switch_port": "se cayó su puerto del switch",
    "firewall_rule": "una regla de firewall bloqueó el puerto del clúster",
    "dns": "un cambio de DNS mandó a sus pares a una dirección equivocada",
    "gc_pause": "pausas largas del recolector de basura",
    "disk_full": "su disco está casi lleno y cada escritura se arrastra",
    "noisy_neighbour": "un vecino ruidoso le roba la CPU",
}

STAGES = [
    StageText("Una copia",
              "Reto: cada nodo guarda su propia copia y las lecturas no ven la última escritura.",
              "Etapa 1: escribe en W=2 de 3 réplicas, lee de R=2"),
    StageText("Quórums",
              "Reto: un nodo que estuvo caído vuelve con datos viejos. Ponlo al día.",
              "Etapa 2: hinted handoff y read repair"),
    StageText("Quórums + reparación",
              "Resuelto: las lecturas ven la última escritura y las réplicas se ponen al día.",
              "Todas las etapas hechas"),
]

GOALS = {
    "stale": GoalText("Lect. viejas = 0", "usa quórums: W + R > N"),
    "answered": GoalText("Respondidas ≥ 99%", "espera a W o R, no a todas"),
    "sync": GoalText("Al día ≥ 99%", "hinted handoff"),
    "msgs": GoalText("Msgs/op < 10", "envía menos mensajes"),
}

LEGEND = {"in_sync": "al día", "behind": "atrasado", "down": "caído", "request": "petición de cliente",
          "message": "mensaje", "dropped": "perdido", "limit": "límite"}

STRINGS = {
    # incidentes
    "crashed": "{node} se cayó: {cause}",
    "cut_off": "{node} quedó aislado: {cause}",
    "slowed": "{node} va lento: {cause}",
    "back": "{node} ha vuelto",
    "fast": "{node} vuelve a ir rápido",
    "warn_stale": "{n} lecturas no vieron la última escritura",
    # el panel
    "tile_stale": "Viejas",
    "tile_answered": "Servido",
    "tile_sync": "Al día",
    "bar_clients": "Clientes",
    "bar_nodes": "Nodos",
    "messages": "Mensajes",
    "limit": "10 msgs/op",
    "chart_limit": "10/op",
    "head_down": "{node} caído: {n} claves atrasadas",
    "head_slow": "{node} lento: el quórum lo salta",
    "head_sync": "{share:.0%} de las claves al día",
    "head_ok": "Cada clave al día en 3 réplicas",
    "head_stale": "{n} lecturas viejas en 10 s",
    "note_chart": "Gráfica: mensajes entre nodos por segundo.",
    # el dibujo
    "state_sick": "{state}: {node}",
    # errores en tu código
    "no_store": "QuorumNode debe guardar sus datos en self.store",
}

LESSON = Lesson(
    title="Quórums",
    one_liner="Guarda cada clave en N nodos, escribe en W, lee de R: con W + R > N, las lecturas ven la última escritura.",
    learn=(
        "Replicación sin líder (Amazon Dynamo, Cassandra, Riak): cualquier nodo puede recibir una "
        "petición y coordinarla. Envía una escritura a las N réplicas de la clave y responde cuando W "
        "la confirmaron; una lectura pregunta a las réplicas y responde con la más nueva de R respuestas.",
        "Si W + R > N, cada quórum de lectura se solapa con cada quórum de escritura en al menos un "
        "nodo, así que una lectura siempre encuentra la última escritura confirmada. Con N=3, W=2, R=2 "
        "un nodo puede estar caído sin que nadie lo note.",
        "Las versiones deciden qué respuesta es la más nueva: aquí, una marca de tiempo más el id del "
        "nodo. Los sistemas reales usan relojes vectoriales o relojes lógicos híbridos, porque los "
        "relojes de verdad se desvían.",
        "Los quórums aseguran las lecturas, pero un nodo que estuvo caído sigue con datos viejos. El "
        "read repair arregla una réplica atrasada cuando una lectura la ve; el hinted handoff guarda "
        "las escrituras que se perdió una réplica y se las entrega cuando vuelve; la anti-entropía "
        "(árboles de Merkle) compara réplicas en segundo plano.",
    ),
    watch_for=(
        "Una copia: las lecturas caen en un nodo que nunca vio la escritura; la tarjeta Viejas se pone roja.",
        "Quórums: ninguna lectura vieja, ni con un nodo caído; pero cuando vuelve, Al día se queda bajo el 99%.",
        "Solo read repair arregla las claves que alguien lee: la mayoría siguen atrasadas mucho tiempo.",
        "Quórums + reparación: las pistas llegan al nodo en cuanto vuelve, y Al día regresa al 100%.",
    ),
    build=(
        ("Apache Cassandra: el nivel de consistencia por petición",
         "CONSISTENCY QUORUM;   -- en cqlsh, antes de SELECT * FROM orders WHERE id = ?;"),
        ("Riak: N, R y W por bucket",
         "curl -XPUT http://riak:8098/buckets/orders/props \\\n"
         "     -H 'Content-Type: application/json' -d '{\"props\": {\"n_val\": 3, \"r\": 2, \"w\": 2}}'"),
        ("Espera las primeras W de N respuestas (asyncio)",
         "acks = 0\n"
         "for done in asyncio.as_completed(tasks):\n"
         "    acks += await done\n"
         "    if acks >= W:\n"
         "        return True"),
    ),
    checklist=(
        "Elige N, W y R por conjunto de datos: W + R > N para leer la última escritura.",
        "Decide qué pasa si responden menos de W réplicas: fallar, o un quórum flexible con pistas.",
        "Versiona cada valor (relojes vectoriales o HLC) y decide cómo resolver conflictos.",
        "Activa read repair y anti-entropía, y alerta sobre réplicas que siguen atrasadas.",
        "Prueba con un nodo caído y con uno lento: la latencia debe seguir a la W-ésima réplica más rápida.",
    ),
    refs=(
        Ref("Amazon Dynamo (SOSP 2007)",
            "https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf",
            "Quórums, quórums flexibles, hinted handoff, relojes vectoriales y anti-entropía con árboles de Merkle (en inglés)."),
        Ref("Apache Cassandra: how data is distributed and replicated",
            "https://cassandra.apache.org/doc/latest/cassandra/architecture/dynamo.html",
            "Replicación, consistencia ajustable, hinted handoff y read repair en Cassandra (en inglés)."),
        Ref("Riak KV: replication properties",
            "https://docs.riak.com/riak/kv/latest/developing/app-guide/replication-properties/index.html",
            "N, R y W por bucket, y qué te dan (en inglés)."),
        Ref("Jepsen: consistency models",
            "https://jepsen.io/consistency",
            "Qué significa exactamente «las lecturas ven la última escritura» (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/quorum/es/main.py y mira cómo la tarjeta Viejas baja a cero.",
        "Luego espera una caída: ¿qué le pasa a Al día cuando el nodo vuelve?",
        "Haz la etapa 2 y mira cómo las pistas llegan al nodo que volvió.",
    ),
)

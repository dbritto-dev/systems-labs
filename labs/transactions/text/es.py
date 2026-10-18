"""Laboratorio transactions, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Transacciones (Gossip Glomers #6)"
SUMMARY = "Gossip Glomers #6: un almacén clave/valor replicado con transacciones, siempre disponible."
PARAMS = {"rate": "transacciones de clientes por segundo"}

INCIDENT = IncidentText("Partición", "la partición", "la próxima partición")
VERBS = {"split": "CORTE", "heal": "UNIDA"}
CAUSES = {
    "tor_switch": "falló el switch del rack de un nodo",
    "firewall_port": "una regla del firewall bloqueó el puerto de replicación de un nodo",
    "nic_drops": "la tarjeta de red de un nodo empezó a perder paquetes",
    "zone_link": "una zona de la nube perdió su enlace con las otras dos",
}

STAGES = [
    StageText("Un solo nodo",
              "Reto: las escrituras se quedan en el nodo que las recibe. Envíalas a los demás nodos.",
              "Etapa 1 (6b): replica cada escritura en los demás nodos"),
    StageText("Replicado",
              "Reto: las escrituras durante una partición se pierden. Reenvíalas hasta que confirmen.",
              "Etapa 2 (6b): reenvía hasta que confirmen; gana el sello más nuevo"),
    StageText("Read uncommitted",
              "Reto: se leen valores que la propia transacción sobrescribió. Replica txns enteras.",
              "Etapa 3 (6c): replica valores finales por txn, de una vez"),
    StageText("Read committed",
              "Resuelto: cada nodo se pone al día tras las particiones y nadie ve valores intermedios.",
              "Todas las etapas hechas"),
]

GOALS = {
    "fresh": GoalText("Al día ≥ 95%", "replica cada escritura"),
    "answered": GoalText("Responde ≥ 99%", "no esperes a otro nodo"),
    "caught_up": GoalText("Recupera ≥ 99%", "reenvía hasta que confirmen"),
    "g0": GoalText("Sin escr. G0", "un sello por txn"),
    "g1b": GoalText("Sin lect. G1", "replica txns enteras"),
}

LEGEND = {"up_to_date": "al día", "behind": "atrasado", "g1b_read": "anomalía G0/G1", "transaction": "transacción",
          "replication": "replicación", "dropped": "perdido", "partition": "partición"}

STRINGS = {
    # incidentes
    "cut_off": "un nodo queda aislado: {cause}",
    "whole_again": "la red vuelve a estar entera",
    "warn_g1b": "n{node} mostró un valor intermedio de la clave {which}",
    "warn_g1a": "n{node} mostró un valor de la clave {which} escrito por una transacción abortada",
    "warn_g1c": "n{node}: dos transacciones leyeron cada una la escritura de la otra (clave {which})",
    "warn_g0": "n{node} intercaló las escrituras de dos transacciones (clave {which})",
    # valores de los objetivos
    "none": "ninguna",
    "seen": "{n} vistas",
    # el panel
    "tile_fresh": "Al día",
    "tile_g1b": "G0/G1",
    "tile_answers": "Resp.",
    "messages": "Mensajes",
    "bar_clients": "Clientes",
    "bar_nodes": "Nodos",
    "head_g1b": "G1b: un lector vio un valor sobrescrito",
    "head_g1a": "G1a: un lector vio una escritura abortada",
    "head_g1c": "G1c: dos transacciones leyeron la escritura de la otra",
    "head_g0": "G0: un nodo intercaló las escrituras de dos transacciones",
    "head_cut": "n{node} aislado: la replicación espera",
    "head_behind": "Hay nodos atrasados ({fresh:.1%} al día)",
    "head_ok": "Todos los nodos están al día",
    "note_chart": "Gráfica: mensajes de replicación/s.",
    # el dibujo
    "state_cut": "n{node} aislado",
    # errores en tu código
    "no_store": "TxnNode debe guardar su almacén clave/valor en self.store (un dict)",
    # el dibujo de carriles (lo que ven los clientes): estados bajo el clúster, 13 letras como mucho
    "lanes_g1b": "LECTURA G1b",
    "lanes_g1a": "LECTURA G1a",
    "lanes_g1c": "LECTURA G1c",
    "lanes_g0": "ESCRIT. G0",
    # el dibujo de pares: bajo un nodo que acaba de mostrar una anomalía
    "peer_anomaly": "n{node} {kind}",
}

LESSON = Lesson(
    title="Transacciones (Gossip Glomers #6)",
    one_liner="Un almacén clave/valor replicado que responde cada transacción, incluso aislado, y aun así nunca muestra trabajo a medias.",
    learn=(
        "Disponibilidad total: cada nodo responde cada transacción por su cuenta, incluso durante una "
        "partición. Así que los nodos no pueden coordinarse antes de responder; replican después y se "
        "ponen al día más tarde.",
        "El nivel read uncommitted solo prohíbe las escrituras sucias (G0): escrituras "
        "de dos transacciones que se entrelazan formando un ciclo. Un sello por transacción (tiempo, "
        "nodo), y que gane la última escritura según ese sello en cada nodo, da a cada clave el mismo "
        "orden de escrituras en todas partes.",
        "El nivel read committed prohíbe además las lecturas abortadas (G1a), las lecturas "
        "intermedias (G1b) y los ciclos de flujo de información (G1c). Una lectura intermedia ve un valor "
        "que la propia transacción sobrescribió: se cuela cuando las escrituras viajan una a una y un "
        "lector se ejecuta entre ellas.",
        "La solución es replicar transacciones enteras: solo su valor final por clave, aplicado de una "
        "vez en el otro nodo.",
    ),
    watch_for=(
        "Un solo nodo: los nodos siguen naranjas (atrasados): cada uno solo tiene las escrituras de sus clientes.",
        "Replicado: vuelven a azul, hasta una partición; después algunas claves nunca se ponen al día.",
        "Read uncommitted: todos se ponen al día, pero hay destellos rojos: lectores que ven valores intermedios.",
        "Read committed: sin destellos rojos, y cada nodo se pone al día tras cada partición.",
    ),
    build=(
        ("Maelstrom: ejecuta el reto real contra tu propio binario",
         "./maelstrom test -w txn-rw-register --bin ./my-txn --node-count 2 --concurrency 2n \\\n"
         "    --time-limit 20 --rate 1000 --consistency-models read-committed \\\n"
         "    --availability total --nemesis partition"),
        ("Gana la última escritura, con un sello por transacción",
         "stamp = (self.now(), self.rank, next(self.counter))\n"
         "for key, value in final_writes.items():\n"
         "    if stamp > self.stamps.get(key, ()):\n"
         "        self.store[key], self.stamps[key] = value, stamp"),
    ),
    checklist=(
        "Apunta qué anomalías prohíbe tu almacén (G0, G1a, G1b, G1c...) y pruébalas.",
        "Replica unidades de trabajo (transacciones), no escrituras sueltas.",
        "Da a cada escritura un orden total en el que coincidan todas las réplicas (sellos, versiones o un log).",
        "Nunca descartes la replicación: guárdala hasta que la confirmen.",
        "Si prometes disponibilidad, nunca esperes a otro nodo antes de responder.",
    ),
    refs=(
        Ref("Fly.io: Gossip Glomers, challenge #6a Totally-Available Transactions",
            "https://fly.io/dist-sys/6a/",
            "El reto original y sus partes 6b y 6c (en inglés)."),
        Ref("Jepsen: Read Committed",
            "https://jepsen.io/consistency/models/read-committed",
            "Qué prohíbe read committed: G0, G1a, G1b, G1c (en inglés)."),
        Ref("Jepsen: Read Uncommitted",
            "https://jepsen.io/consistency/models/read-uncommitted",
            "El modelo más débil: sin escrituras sucias (G0) (en inglés)."),
        Ref("Jepsen: G1b, intermediate read",
            "https://jepsen.io/consistency/phenomena/g1b",
            "La anomalía que elimina la última etapa, con ejemplos (según las definiciones de Adya) (en inglés)."),
        Ref("Maelstrom: the txn-rw-register workload",
            "https://github.com/jepsen-io/maelstrom/blob/main/doc/workloads.md",
            "El mensaje txn y sus microoperaciones (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/transactions/es/main.py y mira cómo los nodos se ponen azules.",
        "Luego espera una partición: ¿qué claves nunca se ponen al día, y por qué?",
        "Haz la etapa 3 y mira cómo dejan de aparecer los destellos rojos.",
    ),
)

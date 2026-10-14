"""Laboratorio raft, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Raft"
SUMMARY = "Raft: elige un líder entre 5 nodos y no pierdas nunca un comando consolidado, con caídas y particiones."
PARAMS = {"rate": "comandos de clientes por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"split": "CORTE", "heal": "UNIDA", "crash": "CAÍDA", "back": "VUELVE", "slow": "LENTA",
         "fast": "RÁPIDA"}
CAUSES = {
    "tor_switch": "falló un switch top-of-rack",
    "zone_link": "una zona de la nube perdió el enlace con las demás",
    "firewall_rule": "una regla de firewall bloqueó el puerto del clúster",
    "kernel_panic": "un kernel panic",
    "oom_killed": "el OOM killer detuvo el proceso",
    "host_reboot": "el host se reinició por un parche de seguridad",
    "congested_link": "un enlace congestionado entre los racks",
    "noisy_neighbour": "un vecino ruidoso está saturando la red",
}

STAGES = [
    StageText("Sin líder",
              "Reto: nadie lidera, así que todo comando falla. Elige un líder con RequestVote.",
              "Etapa 1: timeouts de elección aleatorios, RequestVote, latidos"),
    StageText("Elección de líder",
              "Reto: el líder confirma al cliente comandos que solo él tiene. Replícalos en una mayoría.",
              "Etapa 2: AppendEntries, consolida cuando una mayoría tiene la entrada"),
    StageText("Replicación del log",
              "Reto: al cerrarse la partición, el líder viejo sobrescribe entradas consolidadas.",
              "Etapa 3: renuncia ante un término mayor, rechaza a los líderes viejos"),
    StageText("Seguro",
              "Resuelto: un líder, cada comando consolidado en una mayoría, nada perdido con particiones.",
              "Todas las etapas hechas"),
]

GOALS = {
    "leader": GoalText("Hay líder", "elige uno: RequestVote"),
    "election": GoalText("Elige < 2s", "preséntate tras el timeout"),
    "committed": GoalText("Consolidados 99%", "confirma tras la mayoría"),
    "safe": GoalText("Nada perdido", "rechaza términos viejos"),
    "available": GoalText("Disponible 95%", "redirige al líder"),
}

LEGEND = {"leader": "líder", "follower": "seguidor", "candidate": "candidato", "down": "caído",
          "request": "comando de cliente", "append": "AppendEntries", "vote": "RequestVote",
          "dropped": "perdido", "partition": "partición"}

STRINGS = {
    # incidentes
    "cut_off": "{node} queda aislado con {other}: {cause}",
    "whole": "la red vuelve a estar entera",
    "crashed": "{node} se cayó: {cause}",
    "restarted": "{node} se reinició con su log",
    "slow": "la red va {x:.0f}x más lenta: {cause}",
    "fast": "la red vuelve a ir rápida",
    "warn_lost": "{n} comandos consolidados perdidos",
    "warn_wrong": "{n} comandos confirmados al cliente y nunca consolidados",
    # valores de los objetivos
    "none": "ninguno",
    "never": "nunca",
    "lost_n": "{n} perdidos",
    "wrong_n": "{n} sin guardar",
    # el panel
    "tile_leader": "Líder",
    "tile_term": "Término",
    "tile_lost": "Perdidos",
    "bar_clients": "Clientes",
    "bar_nodes": "Nodos",
    "messages": "Mensajes",
    "head_split": "{node} aislado; líder {leader}, término {term}",
    "head_down": "{node} caído; líder {leader}, término {term}",
    "head_electing": "Sin líder: eligiendo (término {term})",
    "head_ok": "{leader} lidera el término {term}",
    "note_chart": "Gráfica: mensajes entre nodos por segundo.",
    # errores en tu código
    "no_state": "RaftNode debe guardar self.current_term, self.voted_for, self.log y self.role (falta {name})",
}

LESSON = Lesson(
    title="Raft",
    one_liner="Acordar un único log ordenado entre 5 nodos: un líder por término, y un comando está a salvo cuando lo tiene una mayoría.",
    learn=(
        "Términos y elecciones: el tiempo se divide en términos, cada uno con un líder como mucho. Un "
        "seguidor que no oye a nadie durante un timeout de elección aleatorio se hace candidato, sube "
        "el término y pide votos; cada nodo vota una vez por término, así que solo un candidato puede "
        "ganar una mayoría.",
        "Replicación del log: el líder añade cada comando a su log y envía AppendEntries a los "
        "seguidores. Cuando una mayoría guarda la entrada, está consolidada (committed), y solo entonces "
        "el líder responde al cliente. Un líder que responde antes pierde el comando si se cae.",
        "Seguridad: un líder aislado en una minoría no puede consolidar nada, pero no sabe que lo han "
        "depuesto. Cada mensaje lleva el término: un nodo que ve un término mayor renuncia, y un nodo "
        "rechaza AppendEntries de un término menor. Solo se vota a candidatos cuyo log esté al menos "
        "igual de al día, así que un líder nuevo siempre tiene todas las entradas consolidadas.",
        "Disponibilidad: mientras una mayoría pueda hablar, el clúster sigue funcionando; el lado de "
        "la minoría se detiene hasta que se cierra la partición y luego se pone al día con el líder nuevo.",
    ),
    watch_for=(
        "Sin líder: todos los nodos siguen azules, los clientes reciben redirecciones a nadie y nada se consolida.",
        "Elección de líder: un nodo se pone verde; cuando se cae, puntos naranjas (votos) eligen a otro.",
        "Replicación del log: puntos azules de AppendEntries van del líder a cada seguidor.",
        "Seguro: durante un corte el líder viejo sigue verde pero se detiene; tras UNIDA renuncia enseguida.",
    ),
    build=(
        ("etcd: la biblioteca Raft detrás de Kubernetes",
         "import \"go.etcd.io/raft/v3\"\n"
         "n := raft.StartNode(&raft.Config{ID: 1, ElectionTick: 10, HeartbeatTick: 1,\n"
         "    Storage: storage, MaxSizePerMsg: 1 << 20, MaxInflightMsgs: 256}, peers)"),
        ("La regla que lo mantiene seguro (en cada mensaje)",
         "if msg['term'] > self.current_term:\n"
         "    self.current_term, self.voted_for = msg['term'], None\n"
         "    self.role = 'follower'\n"
         "if msg['type'] == 'append_entries' and msg['term'] < self.current_term:\n"
         "    return reject(term=self.current_term)"),
    ),
    checklist=(
        "Persiste current_term, voted_for y el log antes de responder a cualquier RPC.",
        "Usa timeouts de elección aleatorios (p. ej. 150-300 ms) para que los candidatos no dividan el voto sin fin.",
        "Responde a los clientes solo tras consolidar; deja que reintenten con el mismo id (comandos idempotentes).",
        "Usa un número impar de nodos: 5 aguantan 2 fallos, 4 aguantan solo 1.",
        "Prueba con particiones y caídas, y comprueba la linealizabilidad (Jepsen, Porcupine).",
    ),
    refs=(
        Ref("Ongaro y Ousterhout: In Search of an Understandable Consensus Algorithm (2014)",
            "https://raft.github.io/raft.pdf",
            "El artículo de Raft; la figura 2 es el algoritmo entero en una página (en inglés)."),
        Ref("raft.github.io",
            "https://raft.github.io/",
            "Una visualización interactiva, charlas y una lista de implementaciones (en inglés)."),
        Ref("Ongaro: Consensus: Bridging Theory and Practice (PhD thesis, 2014)",
            "https://github.com/ongardie/dissertation",
            "Cambios de miembros, compactación del log, interacción con clientes y las pruebas (en inglés)."),
        Ref("etcd-io/raft",
            "https://github.com/etcd-io/raft",
            "Una biblioteca Raft en producción (etcd, Kubernetes, CockroachDB) (en inglés)."),
        Ref("Jepsen analyses",
            "https://jepsen.io/analyses",
            "Cómo sistemas de consenso reales perdieron datos con particiones, y por qué (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/raft/es/main.py y mira cómo un líder se pone verde.",
        "Luego mira el primer corte: ¿el líder viejo sigue respondiendo a clientes en el lado pequeño?",
        "Prueba --set rate=40: ¿tu líder agrupa entradas en menos AppendEntries?",
    ),
)

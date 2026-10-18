"""Laboratorio paxos_consensus, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Paxos"
SUMMARY = "Paxos: 5 nodos acuerdan un único log de comandos aunque varios propongan a la vez, con caídas, pérdidas y particiones."
PARAMS = {"rate": "comandos de clientes por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"crash": "CAÍDA", "back": "VUELVE", "lossy": "PIERDE", "clean": "LIMPIA", "split": "CORTE",
         "heal": "UNIDA", "pause": "PAUSA", "wake": "SIGUE"}
CAUSES = {
    "oom_killed": "el OOM killer detuvo el proceso",
    "kernel_panic": "un kernel panic",
    "spot_reclaimed": "la nube recuperó su instancia spot",
    "host_reboot": "el host se reinició por un parche de seguridad",
    "disk_failed": "se reinició la controladora de su disco",
    "hypervisor_fault": "un fallo del hipervisor",
    "flapping_link": "un enlace intermitente entre los racks",
    "nic_firmware": "un firmware de la tarjeta de red con errores descarta paquetes",
    "congested_link": "un enlace congestionado entre las zonas",
    "tor_switch": "falló un switch top-of-rack",
    "zone_link": "una zona de la nube perdió el enlace con las demás",
    "firewall_rule": "una regla de firewall bloqueó el puerto del clúster",
    "gc_pause": "una pausa total del recolector de basura",
    "vm_migration": "una migración en vivo congeló su máquina virtual",
    "disk_stall": "un fsync se atascó en un disco ocupado",
}

STAGES = [
    StageText("Gana la primera propuesta",
              "Reto: dos nodos proponen a la vez para una posición; los nodos deciden comandos distintos.",
              "Etapa 1: boletas, preparar/prometer y luego aceptar"),
    StageText("Paxos por posición",
              "Reto: es seguro, pero los proponentes se pisan y cada comando cuesta dos idas y vueltas.",
              "Etapa 2: un líder, fase 1 una vez, no-ops en posiciones vacías"),
    StageText("Multi-Paxos",
              "Resuelto: un mismo log en todos, nada perdido, una ida y vuelta por comando.",
              "Todas las etapas hechas"),
]

GOALS = {
    "agree": GoalText("Desacuerdos = 0", "preparar y aceptar: boletas"),
    "kept": GoalText("Perdidos = 0", "adopta valores aceptados"),
    "live": GoalText("Decidido < 2s 95%", "lidera; espera al azar"),
    "cheap": GoalText("Msgs/cmd ≤ 16", "sin fase 1 mientras lideras"),
}

LEGEND = {"leader": "líder", "node": "nodo", "candidate": "candidato", "split": "decidió distinto",
          "down": "caído", "paused": "en pausa", "request": "comando de cliente", "propose": "proponer", "phase1": "preparar/prometer",
          "phase2": "aceptar/aceptado", "decide": "decidir", "dropped": "perdido"}

STRINGS = {
    # incidentes
    "crashed_mid": "{node} se cayó a mitad de una ronda: {cause}",
    "crashed": "{node} se cayó: {cause}",
    "restarted": "{node} se reinició con su disco",
    "cut_off": "{node} queda aislado con {other}: {cause}",
    "whole": "la red vuelve a estar entera",
    "paused": "{node} se congeló: {cause}",
    "woke": "{node} despierta, seguro aún de que lidera",
    "lossy": "la red pierde el {pct}% de los mensajes: {cause}",
    "clean": "la red deja de perder mensajes",
    "warn_split": "{n} posiciones decididas de dos formas",
    "warn_lost": "{n} comandos confirmados al cliente y perdidos",
    # valores de los objetivos (la regla ya dice qué se cuenta)
    "split_n": "{n}",
    "lost_n": "{n}",
    # el panel
    "tile_split": "Disputas",
    "tile_lost": "Perdidos",
    "tile_cost": "Msgs/cmd",
    "bar_clients": "Clientes",
    "bar_nodes": "Nodos",
    "messages": "Mensajes",
    "head_split": "Posición {slot} decidida de dos formas",
    "head_hit": "{node} afectado; lidera {leader}, boleta {ballot}",
    "head_leader": "{leader} lidera con la boleta {ballot}",
    "head_duel": "Sin líder: se pisan ({ballot})",
    "head_first": "Sin boletas: gana la primera propuesta",
    "note_chart": "Gráfica: mensajes entre nodos por segundo.",
    # el dibujo del clúster: bajo la cuadrícula
    "state_lossy": "PIERDE {pct}%",
    "state_paused": "EN PAUSA {node}",
    # el dibujo de carriles (lo que ven los clientes): estados bajo el clúster, 13 letras como mucho
    "lanes_split": "DESACUERDO",
    "lanes_lost": "PERDIDO",
    "lanes_stalled": "ATASCADO",
    # el dibujo de pares: bajo el nombre de cada nodo, su boleta (b: boleta); su color es su papel
    "peer_ballot": "{node}\nb{ballot}",
    # errores en tu código
    "no_state": "PaxosNode debe guardar self.promised, self.accepted, self.decided y self.role (falta {name})",
}

LESSON = Lesson(
    title="Paxos",
    one_liner="Acordar un valor por posición del log entre 5 nodos, aunque varios propongan a la vez: boletas, promesas y una mayoría.",
    learn=(
        "Por qué es difícil: dos proponentes envían valores distintos para la misma posición a la vez. Si "
        "cada nodo se queda con el primero que oye, unos nodos deciden un comando y otros el otro, y el "
        "log replicado se parte.",
        "Paxos de un solo valor: un proponente elige una boleta mayor que cualquiera que haya visto y "
        "envía preparar. Un aceptador promete ignorar boletas menores e informa del valor que ya aceptó. "
        "Con una mayoría de promesas, el proponente debe proponer el valor aceptado con la boleta más "
        "alta (puede que ya esté elegido), y si no hay, el suyo. Una mayoría de aceptaciones lo decide. "
        "Dos mayorías siempre comparten un nodo, así que una boleta posterior encuentra el valor elegido.",
        "Vivacidad: dos proponentes pueden superarse uno al otro sin fin (proponentes que se pisan): "
        "cada preparar anula el aceptar del otro. Paxos siempre es seguro, pero solo avanza con un "
        "proponente a la vez; FLP dice que ningún protocolo determinista puede prometer ambas cosas en "
        "un sistema asíncrono.",
        "Multi-Paxos: elige un líder con boletas (una espera aleatoria rompe los empates). Ejecuta la "
        "fase 1 una sola vez para todas las posiciones desde la primera sin decidir, vuelve a proponer lo que "
        "aprende y llena las posiciones vacías con no-ops; después cada comando es una ronda de aceptar. Lo "
        "usan Chubby y Spanner; Raft es la misma idea.",
    ),
    watch_for=(
        "Gana la primera propuesta: puntos morados de proponer compiten; un nodo se pone rojo cuando decidió otro comando.",
        "Paxos por posición: puntos naranjas de preparar/prometer en cada comando, y Msgs/cmd muy por encima de 16.",
        "Multi-Paxos: un líder verde; solo aceptar en azul y decidir en verde, y naranja solo tras un incidente.",
        "La primera caída: el líder nuevo vuelve a proponer las dos posiciones que el viejo hizo aceptar, y llena la posición vacía anterior.",
    ),
    build=(
        ("El aceptador: toda la seguridad de Paxos",
         "def on_prepare(self, ballot, slot):\n"
         "    if ballot > self.promised:\n"
         "        self.promised = ballot          # fsync antes de responder\n"
         "        return promise(self.accepted_from(slot))\n"
         "def on_accept(self, ballot, slot, value):\n"
         "    if ballot >= self.promised:\n"
         "        self.promised, self.accepted[slot] = ballot, (ballot, value)"),
        ("Un proponente debe adoptar lo que aprende",
         "prior = [r.accepted[slot] for r in promises if slot in r.accepted]\n"
         "value = max(prior)[1] if prior else my_value   # gana la boleta más alta"),
    ),
    checklist=(
        "Guarda promised y accepted en disco antes de responder a preparar o aceptar.",
        "Haz las boletas únicas: (ronda, id del nodo), y elige siempre una mayor que cualquiera vista.",
        "Ejecuta la fase 1 una vez por liderazgo para todas las posiciones, y llena las vacías con no-ops.",
        "Usa timeouts de elección y backoff aleatorios para que los proponentes no se pisen sin fin.",
        "Aplica el log en orden, y haz los comandos idempotentes (los clientes reintentan).",
    ),
    refs=(
        Ref("Lamport: Paxos Made Simple (2001)",
            "https://lamport.azurewebsites.net/pubs/paxos-simple.pdf",
            "El algoritmo en once páginas, y Multi-Paxos en la sección 3 (en inglés)."),
        Ref("Chandra, Griesemer, Redstone: Paxos Made Live (2007)",
            "https://static.googleusercontent.com/media/research.google.com/en//archive/paxos_made_live.pdf",
            "Lo que costó poner Multi-Paxos en producción en Chubby, de Google (en inglés)."),
        Ref("Van Renesse, Altinbuken: Paxos Made Moderately Complex (2015)",
            "https://www.cs.cornell.edu/home/rvr/Paxos/paxos.pdf",
            "Multi-Paxos con líderes, posiciones y pseudocódigo para cada papel (en inglés)."),
        Ref("Howard: Distributed consensus revised (tesis doctoral, 2019)",
            "https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-935.pdf",
            "Por qué dos quórums deben cruzarse, y cuándo no hace falta (en inglés)."),
        Ref("Wikipedia: Paxos",
            "https://es.wikipedia.org/wiki/Algoritmo_de_Paxos",
            "Los papeles, los mensajes y las variantes."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/paxos_consensus/es/main.py y mira cómo desaparecen los nodos rojos.",
        "Luego mira los mensajes por comando, y los preparar naranjas en cada comando.",
        "Prueba --set rate=40: ¿la etapa 1 sigue decidiendo a tiempo? ¿y Multi-Paxos?",
    ),
)

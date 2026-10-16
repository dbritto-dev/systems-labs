"""Laboratorio failure_detection, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Detección de fallos"
SUMMARY = "8 nodos deben acordar quién está muerto: halla una caída rápido, no entierres un nodo lento o aislado."
PARAMS = {"rate": "peticiones de clientes por segundo, enrutadas según la vista del clúster"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"crash": "CAÍDA", "back": "VUELVE", "slow": "LENTO", "fast": "RÁPIDO", "lossy": "PIERDE",
         "clean": "LIMPIO", "cut": "CORTE", "healed": "UNIDO"}
CAUSES = {
    "oom_kill": "el kernel lo mató por usar demasiada memoria",
    "kernel_panic": "un kernel panic tras actualizar un driver",
    "host_reboot": "su máquina se reinició por un fallo de hardware",
    "bad_deploy": "un despliegue malo lo tumbó al arrancar",
    "gc_pause": "pausas largas del recolector de basura",
    "noisy_neighbour": "un vecino ruidoso le roba la CPU",
    "disk_full": "su disco está casi lleno y cada escritura se arrastra",
    "bad_cable": "un cable dañado en su rack",
    "nic_firmware": "un firmware defectuoso en su tarjeta de red",
    "duplex_mismatch": "un desajuste de dúplex en su puerto del switch",
    "firewall_rule": "una regla nueva de firewall bloquea a algunos de sus pares",
    "stale_route": "una ruta obsoleta manda parte de su tráfico a ninguna parte",
    "security_group": "un cambio de grupo de seguridad descarta a algunos de sus pares",
}

STAGES = [
    StageText("Timeout fijo",
              "Reto: un timeout de 1 s entierra nodos sanos tras enlaces que pierden. Mide cada enlace.",
              "Etapa 1: phi accrual: juzga un silencio por la historia de cada par"),
    StageText("Phi accrual",
              "Reto: latidos a todos los pares cuestan 28 msgs/s por nodo. Sondea de uno en uno.",
              "Etapa 2: SWIM: un ping por periodo, sondeos indirectos, sospecha antes"),
    StageText("SWIM",
              "Resuelto: caídas halladas en menos de 2.5 s, ningún nodo sano muerto, pocos mensajes.",
              "Todas las etapas hechas"),
]

GOALS = {
    "detect": GoalText("Hallada ≤ 2.5 s", "phi accrual: adapta por par"),
    "false": GoalText("Muertes falsas 0", "phi, luego sondeo indirecto"),
    "msgs": GoalText("Msgs/nodo/s < 10", "SWIM: sondea un par"),
}

LEGEND = {"alive": "vivo", "suspect": "sospechoso", "dead": "declarado muerto", "crashed": "caído, sin detectar",
          "probe": "latido o sondeo", "indirect": "sondeo indirecto", "dropped": "perdido", "limit": "límite"}

STRINGS = {
    # incidentes
    "crashed": "{node} se cayó: {cause}",
    "slowed": "{node} va {x:.0f} veces más lento: {cause}",
    "lossy": "{node} pierde el {share:.0%} de sus mensajes: {cause}",
    "cut_off": "{node} no llega a {peers}: {cause}",
    "back": "{node} ha vuelto",
    "fast": "{node} vuelve a ir rápido",
    "clean": "los enlaces de {node} ya no pierden",
    "healed": "{node} vuelve a llegar a todos",
    "warn_false": "muertes falsas: {nodes}",
    # objetivos
    "no_crash": "no cayó",
    "never": "nunca",
    # el panel
    "tile_found": "Hallada",
    "tile_false": "Falsas",
    "tile_msgs": "Msgs/nodo",
    "bar_clients": "Clientes",
    "bar_nodes": "Nodos",
    "messages": "Mensajes",
    "limit": "10/nodo",
    "chart_limit": "10/nodo",
    "head_false": "{node} dado por muerto, pero vivo",
    "head_unfound": "{node} caído {s:.1f} s: sin detectar",
    "head_found": "{node} caído: hallado en {s:.1f} s",
    "head_slow": "{node} lento, sigue vivo",
    "head_lossy": "{node} pierde, sigue vivo",
    "head_partial": "{node} aislado a medias, vivo",
    "head_suspect": "{node} es sospechoso",
    "head_ok": "Todos vivos, y la vista coincide",
    "note_chart": "Gráfica: mensajes entre nodos por segundo.",
    # el dibujo
    "state_sick": "{state}: {node}",
    "state_lossy": "PIERDE",
    "state_false": "MUERTE FALSA: {node}",
    # el dibujo de carriles (lo que ven los clientes): estados bajo el clúster, 13 letras como mucho
    "lanes_failing": "FALLANDO",
    "lanes_needless": "CAMBIO INÚTIL",
    "lanes_in_use": "{n}/{of} EN USO",
    # el dibujo de pares: bajo cada nodo, lo que el clúster cree de él, corto
    "peer_dead": "{node} muerto",
    "peer_false": "{node} FALSO",
    "peer_down": "{node} caído",
    "peer_suspect": "{node} sospechoso",
    # errores en tu código
    "no_status": "Detector debe guardar self.status: un dict, id del par -> 'alive', 'suspect' o 'dead'",
}

LESSON = Lesson(
    title="Detección de fallos",
    one_liner="Un nodo callado puede estar muerto, lento o tras un enlace malo: halla las caídas rápido sin "
              "enterrar a los vivos.",
    learn=(
        "Un nodo no distingue un par caído de uno lento, ni de un enlace roto: solo ve silencio. Un detector "
        "de fallos convierte el silencio en un veredicto, y todo detector equilibra lo rápido que halla una "
        "caída con lo a menudo que declara muerto a un nodo sano.",
        "Un timeout fijo de latidos elige un punto de ese equilibrio para todos los enlaces: corto, y los "
        "enlaces que pierden mensajes entierran nodos sanos; largo, y cada caída se halla tarde.",
        "El detector phi accrual (Hayashibara y otros; lo usan Cassandra y Akka) guarda los intervalos "
        "recientes entre los latidos de cada par y dice lo improbable que es el silencio actual, según ellos. "
        "Los enlaces estables dan veredictos rápidos; los ruidosos reciben el tiempo que su historia pide.",
        "SWIM (lo usan Consul, Serf y memberlist) deja de mandar latidos a todos: cada nodo hace ping a un par "
        "por periodo, pide a k otros que le hagan ping cuando no responde (un enlace roto no es un nodo "
        "muerto) y sospecha de él antes de declararlo muerto. La carga por nodo no crece con el clúster.",
    ),
    watch_for=(
        "Timeout fijo: los nodos tras los cuatro enlaces que pierden se ponen rojos una y otra vez, y Falsas "
        "nunca se queda en 0.",
        "Sube el timeout a 3 s: no hay más muertes falsas, pero Hallada marca 3 s y mientras tanto fallan "
        "las peticiones de los clientes.",
        "Phi accrual: caídas halladas en menos de un segundo y enlaces que pierden tolerados, pero 28 "
        "mensajes por nodo y segundo, y una partición parcial aún entierra un nodo.",
        "SWIM: pocos mensajes por nodo; los sondeos indirectos (naranja claro) rodean un enlace roto.",
    ),
    build=(
        ("Cassandra: cuán sospechoso debe ser un silencio (cassandra.yaml)",
         "phi_convict_threshold: 12    # 8 por defecto; súbelo en redes ruidosas como EC2"),
        ("Akka: el detector phi accrual de un clúster (application.conf)",
         "akka.cluster.failure-detector {\n"
         "  threshold = 12.0\n"
         "  acceptable-heartbeat-pause = 3 s\n"
         "}"),
        ("HashiCorp memberlist (Go): SWIM con sondeos indirectos",
         "cfg := memberlist.DefaultLANConfig()\n"
         "cfg.ProbeInterval = time.Second\n"
         "cfg.IndirectChecks = 3          // k ayudantes\n"
         "cfg.SuspicionMult = 4           // sospecha tantos periodos (x log n) antes de declararlo muerto"),
    ),
    checklist=(
        "Mide los intervalos entre latidos de cada enlace antes de elegir un timeout: importa la cola, no la media.",
        "Nunca dejes que el silencio de un solo observador decida: pregunta a otros (sondeos indirectos) o espera a que coincidan.",
        "Sospecha antes de declarar muerto, y deja que el nodo sospechoso lo desmienta.",
        "Cuenta los mensajes: los latidos de todos a todos crecen con el cuadrado del clúster.",
        "Alerta de las muertes falsas (nodos declarados muertos que vuelven vivos), no solo de las reales.",
    ),
    refs=(
        Ref("SWIM: Scalable Weakly-consistent Infection-style Process Group Membership Protocol",
            "https://www.cs.cornell.edu/projects/Quicksilver/public_pdfs/SWIM.pdf",
            "Das, Gupta y Motivala (2002): sondeos, sondeos indirectos y sospecha."),
        Ref("The phi accrual failure detector",
            "https://dspace.jaist.ac.jp/dspace/bitstream/10119/4784/1/IS-RR-2004-010.pdf",
            "Hayashibara, Défago, Yared y Katayama (2004)."),
        Ref("Akka: phi accrual failure detector",
            "https://doc.akka.io/libraries/akka-core/current/typed/failure-detector.html",
            "Cómo el umbral y la pausa aceptable dan forma a la detección en la práctica."),
        Ref("Lifeguard: local health awareness for more accurate failure detection",
            "https://arxiv.org/abs/1707.00788",
            "Las mejoras de HashiCorp a SWIM, tal como las usan Consul y Nomad."),
        Ref("Consul: gossip protocol",
            "https://developer.hashicorp.com/consul/docs/architecture/gossip",
            "Pertenencia y detección de fallos basadas en SWIM, en producción."),
    ),
    try_next=(
        "Mira la etapa 0 y luego pon TIMEOUT = 3.0 en labs/failure_detection/es/main.py: ¿qué le pasa a Hallada?",
        "Haz la etapa 1 (phi) y espera una partición parcial: ¿a quién declaran muerto, y quién lo hace?",
        "Haz la etapa 2 y mira cómo los sondeos indirectos rodean los enlaces rotos.",
    ),
)

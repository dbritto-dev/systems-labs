"""Laboratorio vector_clocks_crdts, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Relojes vectoriales y CRDT"
SUMMARY = "Carritos de compra con varios líderes en 5 réplicas: no pierdas altas ni bajas con particiones."
PARAMS = {"rate": "operaciones de dispositivos por segundo (añadir, quitar o leer un carrito)"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"split": "CORTE", "heal": "UNIDA", "offline": "AISLA", "back": "VUELVE", "skew": "RELOJ", "ntp": "HORA"}
CAUSES = {
    "tor_switch": "un switch de rack se reinició tras actualizar su firmware",
    "zone_link": "se cayó el enlace entre dos centros de datos",
    "bgp_flap": "una ruta BGP oscila entre los sitios",
    "fiber_cut": "unas obras cortaron la fibra del sitio",
    "vpn_cert": "caducó el certificado de la VPN entre sitios",
    "isp_outage": "se cayó el proveedor de internet del sitio",
    "ntp_step": "NTP corrigió el reloj de golpe tras una larga deriva",
    "vm_migration": "una migración en vivo de la máquina virtual desajustó el reloj",
    "bad_ntp_server": "un servidor NTP mal configurado dio una hora equivocada",
}

STAGES = [
    StageText("Gana la última escritura",
              "Reto: un carrito editado en dos sitios a la vez pierde altas. Detecta la concurrencia.",
              "Etapa 1: relojes vectoriales y versiones hermanas"),
    StageText("Relojes vectoriales",
              "Reto: no se pierde nada, pero vuelven productos quitados. Haz del carrito un CRDT.",
              "Etapa 2: un conjunto de bajas observadas (ORSet)"),
    StageText("CRDT",
              "Resuelto: todas las réplicas convergen al mismo carrito, sin altas perdidas ni regresos.",
              "Todas las etapas hechas"),
]

GOALS = {
    "lost": GoalText("Perdidas = 0", "relojes vectoriales, no hora"),
    "back": GoalText("Revividas = 0", "un ORSet con lápidas"),
    "sync": GoalText("Iguales ≥ 99%", "difunde cada carrito"),
    "msgs": GoalText("Msgs ≤ 150/s", "difunde menos a menudo"),
}

LEGEND = {"in_sync": "igual", "diverged": "diverge", "lost": "alta perdida / baja revivida",
          "request": "petición de dispositivo", "gossip": "difusión", "dropped": "perdido", "limit": "límite"}

STRINGS = {
    # incidentes
    "split": "la red se partió {sides}: {cause}",
    "healed": "la red vuelve a estar unida",
    "offline": "{node} está aislada pero sigue aceptando escrituras: {cause}",
    "online": "{node} vuelve con carritos viejos",
    "skew_ahead": "el reloj de {node} saltó {s:.0f} s adelante: {cause}",
    "skew_behind": "el reloj de {node} saltó {s:.0f} s atrás: {cause}",
    "ntp_fixed": "el reloj de {node} vuelve a estar en hora",
    "warn_lost": "{n} altas confirmadas desaparecieron",
    "warn_back": "{n} productos quitados volvieron",
    # el panel
    "tile_lost": "Perdidas",
    "tile_back": "Revividas",
    "tile_sync": "Iguales",
    "bar_clients": "Equipos",
    "bar_gossip": "Difusión",
    "messages": "Mensajes",
    "limit": "150/s",
    "chart_limit": "150/s",
    "head_lost": "{n} altas perdidas en 10 s",
    "head_back": "{n} bajas revividas en 10 s",
    "head_split": "Corte {sizes}: los dos escriben",
    "head_offline": "{node} aislada, sigue escribiendo",
    "head_ahead": "reloj de {node}: {s:.0f} s adelantado",
    "head_behind": "reloj de {node}: {s:.0f} s atrasado",
    "head_sync": "{share:.0%} de carritos iguales",
    "head_ok": "Todas las réplicas coinciden",
    "note_chart": "Gráfica: mensajes entre réplicas por segundo.",
    # el dibujo
    "state_skew": "RELOJ {node} {s:+.0f} s",
    # el dibujo de carriles (lo que ven los dispositivos): estados bajo el servidor, 13 letras como mucho
    "lanes_lost": "SE PIERDEN",
    "lanes_back": "REVIVEN",
    "lanes_skew": "RELOJ MAL",
    # el dibujo de pares: bajo cada réplica, cuántos carritos difieren allí, o su reloj, corto
    "peer_differ": "{node}\n{n} distintos",
    "peer_skew": "{node}\nreloj {s:+.0f}s",
    # errores en tu código
    "no_items": "CartNode necesita un método items(cart) que devuelva los productos del carrito",
}

LESSON = Lesson(
    title="Relojes vectoriales y CRDT",
    one_liner="Con varios líderes, las marcas de tiempo pierden escrituras: sigue la causalidad, o usa tipos de datos que se fusionan solos.",
    learn=(
        "Replicación con varios líderes (y sin conexión): cada réplica acepta escrituras por su cuenta "
        "y se lo cuenta a las demás después. Dos réplicas pueden cambiar el mismo carrito a la vez, así "
        "que el sistema tiene que decidir qué hacer con escrituras concurrentes.",
        "Con «gana la última escritura» se queda la versión con la marca de tiempo más nueva y la otra "
        "se pierde en silencio. Las altas concurrentes se pierden, y los relojes mienten: tras un salto "
        "de NTP una escritura vieja puede ganarle a una más nueva. Cassandra y muchas cachés funcionan así.",
        "Un reloj vectorial cuenta las escrituras que ha visto cada réplica ({n0: 3, n2: 1}). Al "
        "comparar dos sabes si una versión ocurrió antes que la otra o si son concurrentes. Guarda las "
        "concurrentes como hermanas y fusiónalas al leer (Dynamo, Riak): no se pierde nada, pero la "
        "unión devuelve productos que un lado había quitado.",
        "Un CRDT es un tipo de datos cuya fusión es conmutativa, asociativa e idempotente: las réplicas "
        "que vieron las mismas actualizaciones tienen el mismo valor, en cualquier orden. Un conjunto de "
        "bajas observadas etiqueta cada alta y solo quita las etiquetas que ha visto: un alta que no vio "
        "sobrevive, y nada de lo quitado vuelve. El precio: guardar lápidas.",
    ),
    watch_for=(
        "Gana la última escritura: cuando la red se une, las altas de un lado desaparecen (rojo); un salto de reloj también.",
        "Relojes vectoriales: Perdidas se queda en 0, pero tras un corte vuelven productos quitados (Revividas en rojo).",
        "Un conjunto de productos quitados sin etiquetas pierde las altas repetidas: un producto añadido otra vez tras quitarlo.",
        "ORSet: las réplicas divergen durante el corte (naranja) y coinciden antes de un segundo tras unirse.",
    ),
    build=(
        ("Riak: guarda hermanas (relojes vectoriales), o deja que un conjunto CRDT las fusione",
         "riak-admin bucket-type create carts '{\"props\":{\"allow_mult\":true}}'\n"
         "riak-admin bucket-type create sets  '{\"props\":{\"datatype\":\"set\"}}'"),
        ("Automerge: un documento CRDT por carrito, fusionado en cualquier orden",
         "doc = Automerge.change(doc, d => { d.items.push(\"milk\") })\n"
         "merged = Automerge.merge(phoneDoc, laptopDoc)"),
        ("Una baja en un ORSet: pon lápida solo a las etiquetas que has visto",
         "def remove(self, item):\n"
         "    self.removed |= self.tags.pop(item, set())"),
    ),
    checklist=(
        "Nunca ordenes escrituras de máquinas distintas solo por la hora del reloj.",
        "Decide por tipo de dato qué significan las escrituras concurrentes: gana el alta, gana la baja, o pregunta.",
        "Prefiere un CRDT (contadores, conjuntos, mapas) a fusionar hermanas a mano.",
        "Planea cómo se recogen las lápidas, y acota el tamaño de lo que difundes.",
        "Prueba con particiones, una réplica aislada durante minutos y un reloj que salta.",
    ),
    refs=(
        Ref("Amazon Dynamo (SOSP 2007)",
            "https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf",
            "El carrito de compra, los relojes vectoriales y las hermanas que fusiona la aplicación (en inglés)."),
        Ref("A comprehensive study of CRDTs (Shapiro et al.)",
            "https://inria.hal.science/inria-00555588/document",
            "Contadores, registros, conjuntos (también el OR-set) y por qué sus fusiones convergen (en inglés)."),
        Ref("Riak KV: causal context",
            "https://docs.riak.com/riak/kv/latest/learn/concepts/causal-context/index.html",
            "Relojes vectoriales, dotted version vectors y hermanas en una base de datos real (en inglés)."),
        Ref("Riak KV: sets",
            "https://docs.riak.com/riak/kv/latest/developing/data-types/sets/index.html",
            "Un conjunto CRDT listo para usar: altas y bajas que se fusionan solas (en inglés)."),
        Ref("Kyle Kingsbury: the trouble with timestamps",
            "https://aphyr.com/posts/299-the-trouble-with-timestamps",
            "Cómo «gana la última escritura» con relojes de pared pierde escrituras confirmadas (en inglés)."),
        Ref("Leslie Lamport: time, clocks, and the ordering of events",
            "https://lamport.azurewebsites.net/pubs/time-clocks.pdf",
            "«Ocurrió antes»: la idea sobre la que se construyen los relojes vectoriales (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/vector_clocks_crdts/es/main.py y mira cómo Perdidas sigue en cero tras un corte.",
        "Luego mira Revividas: ¿qué productos quitados vuelven, y por qué?",
        "Haz la etapa 2 y mira cómo todas las réplicas convergen, sin perder nada y sin que nada vuelva.",
    ),
)

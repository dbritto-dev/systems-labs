"""Laboratorio grow_only_counter, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Contador que solo crece (Gossip Glomers #4)"
SUMMARY = "Gossip Glomers #4: cuenta sumas en 3 nodos sin estado con un almacén KV secuencialmente consistente."
PARAMS = {"rate": "operaciones de clientes por segundo (60% add, 40% read)"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"burst": "PICO", "calm": "CALMA", "slow": "LENTO", "fast": "RÁPIDO"}
CAUSES = {
    "flash_sale": "empezó una venta relámpago",
    "retry_loop": "un cliente reintentó cada suma en bucle",
    "batch_import": "una importación por lotes repitió un día de eventos",
    "congested_link": "un enlace congestionado entre racks",
    "noisy_neighbour": "un vecino ruidoso saturó la red del host",
    "bad_mtu": "un MTU mal configurado fragmentó cada paquete",
}

STAGES = [
    StageText("En memoria",
              "Reto: cada nodo solo cuenta sus propias sumas. Guarda la cuenta en seq-kv, compartida.",
              "Etapa 1: lee la clave, suma y escríbela de vuelta"),
    StageText("Clave compartida",
              "Reto: los nodos pisan las sumas de los demás y el total se queda corto. Usa CAS.",
              "Etapa 2: compare-and-swap, y reintenta si falla"),
    StageText("Compare-and-swap",
              "Reto: cada suma choca con las demás en una sola clave. Dale a cada nodo su clave.",
              "Etapa 3: una clave por nodo; una lectura las suma"),
    StageText("Clave por nodo",
              "Resuelto: sin sumas perdidas ni conflictos: cada nodo escribe solo su propia clave.",
              "Todas las etapas hechas"),
]

GOALS = {
    "stored": GoalText("Cuenta en seq-kv", "guarda la cuenta en seq-kv"),
    "right": GoalText("Sin sumas perdidas", "usa cas, no write"),
    "conflicts": GoalText("Conflictos < 10%", "una clave por nodo"),
    "answered": GoalText("Sumas respondidas", "menos reintentos por suma"),
    "after": GoalText("Bien después", "lecturas al día"),
}

LEGEND = {"node": "nodo", "reads_off": "lecturas mal", "seq_kv": "seq-kv",
          "client_request": "petición de cliente", "kv_request": "petición a kv", "kv_ok": "kv ok",
          "cas_conflict": "conflicto cas"}

STRINGS = {
    # incidentes
    "title_burst": "Pico",
    "title_slow": "Red lenta",
    "back_to_normal": "vuelve a la normalidad",
    "slow_text": "cada mensaje tarda {factor:.1f}x más: {cause}",
    "burst_text": "{factor:.1f}x las sumas: {cause}",
    "warn_conflicts": "chocan el {share:.0%} de los CAS",
    # valores de los objetivos
    "ops": "{n:,} ops",
    # el panel
    "tile_right": "Bien",
    "tile_adds": "Sumas",
    "tile_conflict": "Choques",
    "requests": "Peticiones",
    "bar_clients": "Clientes",
    "bar_kv": "seq-kv",
    "head_conflicts": "Chocan el {share:.0%} de los CAS",
    "head_missing": "Faltan {lost:,} sumas confirmadas",
    "head_off": "Las lecturas no cuadran",
    "head_total": "Total {total:,}: lecturas correctas",
    "head_waiting": "Esperando lecturas",
    "note_chart": "Gráfica: peticiones a seq-kv por segundo.",
    # el dibujo
    "state_conflicts": "CONFLICTOS CAS {share:.0%}",
    "state_burst": "PICO x{factor:.1f}",
    "state_slow": "RED LENTA x{factor:.1f}",
    "state_off": "LECTURAS MAL",
    # errores en tu código
    "stuck": "una petición de cliente lleva más de {seconds:.0f} s esperando: ¿algún handler nunca responde?",
    # el dibujo de carriles (lo que ven los clientes): estados bajo el clúster, 13 letras como mucho
    "lanes_conflicts": "CONFLICTOS",
    "lanes_kv_slow": "KV LENTO",
    # el dibujo en embudo: la red (la puerta), los nodos, seq-kv (el almacén)
    "fan_network": "red",
    "fan_off": "{node} lee mal",
    "fan_conflicts": "CONFLICTOS {share:.0%}",
}

LESSON = Lesson(
    title="Contador que solo crece (Gossip Glomers #4)",
    one_liner="Cuenta sumas en nodos sin estado a través de un almacén clave/valor que puede responder con valores viejos.",
    learn=(
        "Los nodos sin estado guardan la verdad en un almacén compartido. Leer-modificar-escribir no es "
        "seguro ahí: dos nodos leen el mismo valor, los dos suman, y la segunda escritura borra la suma "
        "de la primera. Nada falla; el total simplemente se queda corto.",
        "Compare-and-swap (`cas viejo -> nuevo`) arregla las actualizaciones perdidas: la escritura solo "
        "entra si nadie cambió el valor desde que lo leíste; si no, vuelves a leer y reintentas. Pero en "
        "una sola clave caliente cada suma choca con todas las demás, y un almacén secuencialmente "
        "consistente lo empeora: puede darte un valor viejo, así que tu cas falla aunque nadie más escriba.",
        "Consistencia secuencial: cada cliente ve las operaciones en un mismo orden, y sus propias "
        "escrituras, pero no necesariamente las últimas de los demás. Las lecturas pueden ir atrasadas; "
        "nunca van hacia atrás.",
        "Reparte la clave caliente: dale a cada nodo una clave que solo él escribe, y lee la suma. Un "
        "contador que solo crece es el CRDT más simple: cuentas por nodo que solo crecen y se combinan "
        "sumándolas.",
    ),
    watch_for=(
        "En memoria: cada nodo lee un total distinto y demasiado pequeño; seq-kv no recibe peticiones.",
        "Clave compartida: el total crece, pero más despacio que las sumas; las lecturas pierden sumas confirmadas.",
        "Compare-and-swap: se acumulan conflictos rojos, peor en un pico; las sumas empiezan a dar timeout.",
        "Clave por nodo: nada de rojo; las lecturas cuadran dentro del retraso del almacén.",
    ),
    build=(
        ("Maelstrom: ejecuta el reto real contra tu propio binario",
         "./maelstrom test -w g-counter --bin ./my-counter --node-count 3 \\\n"
         "    --rate 100 --time-limit 20 --nemesis partition"),
        ("Un bucle de compare-and-swap (y por qué no basta en una clave caliente)",
         "while True:\n"
         "    old = await kv.read(KEY)\n"
         "    try:\n"
         "        await kv.cas(KEY, old, old + delta, create=True)\n"
         "        break\n"
         "    except RPCError as e:\n"
         "        if e.code != 22: raise"),
        ("Redis: un campo de hash por nodo, y la suma al leer",
         "await redis.hincrby('views', node_id, delta)\n"
         "total = sum(map(int, (await redis.hvals('views'))))"),
    ),
    checklist=(
        "Nunca hagas leer-modificar-escribir sobre estado compartido sin protección (cas, una transacción o un único escritor).",
        "Conoce la consistencia de tu almacén: ¿una lectura puede devolver un valor viejo? ¿Puede desaparecer tu propia escritura?",
        "Reparte las claves calientes: un escritor por clave, y combina al leer (contadores, conjuntos, totales por fragmento).",
        "Cuenta reintentos y conflictos; alerta cuando una clave está disputada.",
        "Responde al cliente solo cuando su actualización sea duradera.",
    ),
    refs=(
        Ref("Fly.io: Gossip Glomers, challenge #4 Grow-Only Counter",
            "https://fly.io/dist-sys/4/",
            "El reto original (en inglés)."),
        Ref("Maelstrom: services (seq-kv, lin-kv)",
            "https://github.com/jepsen-io/maelstrom/blob/main/doc/services.md",
            "read, write y cas, y su consistencia (en inglés)."),
        Ref("Jepsen: sequential consistency",
            "https://jepsen.io/consistency/models/sequential",
            "Qué promete un almacén secuencialmente consistente, y qué no (en inglés)."),
        Ref("Shapiro et al.: A comprehensive study of CRDTs (2011)",
            "https://inria.hal.science/inria-00555588/document",
            "El G-Counter y sus amigos (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/grow_only_counter/es/main.py y mira la tarjeta 'Bien': ¿por qué sigue roja?",
        "Haz la etapa 2 y espera un pico: ¿qué pasa con los conflictos y con las sumas?",
        "Prueba --set rate=40 con tu etapa 3: ¿empeora algo?",
    ),
)

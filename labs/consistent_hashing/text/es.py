"""Laboratorio consistent_hashing, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Hashing consistente"
SUMMARY = "8 cachés delante de una base de datos. Reparte las claves para que un cambio mueva pocas."
PARAMS = {"rate": "lecturas de claves por segundo"}

INCIDENT = IncidentText("Cambio", "el cambio", "el próximo cambio")
VERBS = {"lost": "CAÍDO", "back": "NUEVO", "join": "ENTRA", "leave": "SALE", "stop": "PARA", "start": "VUELVE"}
CAUSES = {
    "kernel_panic": "un kernel panic",
    "spot_reclaimed": "la nube recuperó su instancia spot",
    "oom_killed": "se quedó sin memoria y el sistema paró la caché",
    "disk_full": "se llenó su disco",
    "evening_peak": "el pico de la tarde",
    "sale_capacity": "capacidad extra para una oferta",
    "autoscaler_cpu": "el autoescalado vio la CPU alta",
    "rolling_deploy": "un despliegue escalonado",
    "config_restart": "un cambio de configuración pide reiniciar",
    "kernel_patch": "un parche de seguridad del kernel",
}

STAGES = [
    StageText("Módulo",
              "Reto: un nodo más o menos mueve casi todas las claves; la BD se inunda. Usa un anillo.",
              "Etapa 1: pon los nodos en un anillo de hash en Router"),
    StageText("Anillo de hash",
              "Reto: ya se mueven pocas claves, pero algunos nodos tienen muchas más que otros.",
              "Etapa 2: dale a cada nodo ~200 nodos virtuales"),
    StageText("Anillo + nodos virtuales",
              "Resuelto: un cambio mueve ~1/N de las claves, y cada nodo tiene su parte justa.",
              "Todas las etapas hechas"),
]

GOALS = {
    "balance": GoalText("Claves/nodo ≤ 1.4x", "añade nodos virtuales"),
    "moved": GoalText("Movidas ≤ 3/N", "usa un anillo de hash"),
    "hits": GoalText("Aciertos ≥ 90%", "mueve menos claves"),
    "db": GoalText("Carga BD ≤ 2x", "mueve menos claves"),
}

LEGEND = {"fair": "carga justa", "busy": "cargado", "hot": "saturado", "out": "fuera", "removed": "recién quitado", "read": "lectura",
          "miss": "fallo", "limit": "límite"}

STRINGS = {
    # incidentes
    "title_crash": "Nodo caído",
    "title_scale": "Escalado",
    "title_deploy": "Reinicio",
    "lost": "{node} se cae: {cause}",
    "lost_plain": "se cae un nodo: {cause}",
    "replaced": "{node} se sustituye, con la caché vacía",
    "replaced_plain": "el nodo se sustituye, con la caché vacía",
    "join": "{node} entra: {cause}",
    "join_plain": "entra un nodo: {cause}",
    "leave": "{node} vuelve a salir",
    "leave_plain": "el nodo extra vuelve a salir",
    "stop": "{node} se para: {cause}",
    "stop_plain": "se para un nodo: {cause}",
    "start": "{node} vuelve, con la caché vacía",
    "start_plain": "el nodo vuelve, con la caché vacía",
    # valores de los objetivos
    "per_n": "{value:.1f}/N",
    # el panel
    "tile_hits": "Aciert.",
    "tile_db": "BD/s",
    "tile_spread": "Reparto",
    "bar_cache": "Caché",
    "bar_db": "BD",
    "limit": "BD {limit:.0f}/s",
    "chart_limit": "BD {limit:.0f}/s",
    "reads": "Lecturas",
    "head_change": "{node}: {moved:.0%} claves movidas, {hits:.0%} aciertos",
    "head_hot": "{node} tiene {spread:.1f}x su parte de claves",
    "head_ok": "{hits:.0%} aciertos; la base de datos lee {db:.0f}/s",
    "note_chart": "Gráfica: lecturas/s a la BD; en rojo, rechazadas.",
    "note_nodes": "Nodos: color según su parte frente a la media.",
    # el dibujo de carriles (lo que ven los clientes): estados bajo el clúster, 13 letras como mucho
    "lanes_hits": "ACIERTOS {share:.0%}",
    "lanes_misses": "FALLOS {share:.0%}",
    # el dibujo en embudo: el enrutador (la puerta), los servidores de caché, la base de datos (el almacén)
    "fan_router": "enrutador",
    "fan_db": "{state} BD {db}/s",
    # errores en tu código
    "bad_node": "node_for devolvió '{node}', que ahora no está en el clúster ({live})",
}

LESSON = Lesson(
    title="Hashing consistente",
    one_liner="Reparte las claves entre servidores de caché para que añadir o perder uno mueva solo su parte.",
    learn=(
        "hash(key) % N reparte bien las claves, pero cuando N cambia casi todas cambian de servidor: "
        "de 8 a 7 nodos se mueven unas 7 de cada 8. Cada clave movida es un fallo en un servidor frío, "
        "así que a la base de datos le llega de golpe casi todo el tráfico que absorbía la caché.",
        "Un anillo de hash pone cada nodo en un círculo, en hash(node). Una clave es del primer nodo "
        "que hay en el sentido de las agujas del reloj desde hash(key). Cuando un nodo sale, solo se "
        "mueven sus claves, al nodo siguiente; cuando entra uno, solo le quita claves a su vecino. Se "
        "mueve más o menos 1/N de las claves.",
        "Con un punto por nodo los arcos son desiguales: algunos nodos tienen dos o tres veces su "
        "parte. Los nodos virtuales ponen cada nodo muchas veces en el anillo (de 100 a 200 puntos), "
        "así que cada uno tiene más o menos 1/N, y un nodo que sale reparte sus claves entre todos los "
        "demás, no solo uno.",
        "Alternativas con el mismo fin: rendezvous hashing (el mayor peso aleatorio), jump consistent "
        "hash (sin memoria, pero los nodos van numerados de 0 a N-1) y la tabla de búsqueda de Maglev.",
    ),
    watch_for=(
        "Módulo: en cada cambio casi todos los puntos se vuelven rojos (fallos) y la barra de la BD pasa su límite.",
        "Anillo de hash: un cambio apenas se nota, pero algunos nodos siguen naranjas o rojos: tienen más claves.",
        "Anillo + nodos virtuales: todos los nodos siguen azules, y un cambio solo causa unos pocos fallos.",
        "Los objetivos: claves movidas y reparto son cosa de tu enrutador; aciertos y carga de la BD, lo que notan los usuarios.",
    ),
    build=(
        ("Un anillo con nodos virtuales (Python)",
         "ring = sorted((stable_hash(f'{node}#{i}'), node) for node in nodes for i in range(200))\n"
         "points = [h for h, _ in ring]\n\n"
         "def node_for(key):\n"
         "    i = bisect.bisect_left(points, stable_hash(key)) % len(ring)\n"
         "    return ring[i][1]"),
        ("Jump consistent hash (Lamping y Veach)",
         "def jump(key: int, buckets: int) -> int:\n"
         "    b, j = -1, 0\n"
         "    while j < buckets:\n"
         "        b = j\n"
         "        key = (key * 2862933555777941757 + 1) % 2**64\n"
         "        j = int((b + 1) * (2**31 / ((key >> 33) + 1)))\n"
         "    return b"),
    ),
    checklist=(
        "Nunca enrutes con hash(key) % N si N puede cambiar: cuenta las claves que se mueven en un cambio.",
        "Usa un hash estable entre procesos y versiones (md5, xxhash, murmur); no el hash() de Python.",
        "Dale a cada nodo de 100 a 200 nodos virtuales, o dales peso según su capacidad.",
        "Mide el reparto: claves y peticiones del nodo más cargado frente a la media.",
        "Cuenta con una ráfaga de fallos en cada cambio de todas formas, y que la base de datos la aguante.",
        "Las claves calientes son otro problema: ningún hash reparte una sola clave muy popular.",
    ),
    refs=(
        Ref("Karger et al.: Consistent hashing and random trees (1997)",
            "https://www.cs.princeton.edu/courses/archive/fall09/cos518/papers/chash.pdf",
            "El artículo original, pensado para cachés web; el origen de Akamai (en inglés)."),
        Ref("Amazon Dynamo (2007)",
            "https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf",
            "Un anillo con nodos virtuales en producción, y por qué pesan los nodos por capacidad (en inglés)."),
        Ref("Lamping y Veach: A fast, minimal memory, consistent hash algorithm (2014)",
            "https://arxiv.org/abs/1406.2294",
            "Jump consistent hash: unas pocas líneas, sin anillo (en inglés)."),
        Ref("Ably: Implementing efficient consistent hashing",
            "https://ably.com/blog/implementing-efficient-consistent-hashing",
            "Cómo reparte Ably los canales en un clúster que cambia (en inglés)."),
        Ref("Discord: How Discord scaled Elixir to 5,000,000 concurrent users",
            "https://discord.com/blog/how-discord-scaled-elixir-to-5-000-000-concurrent-users",
            "Un anillo de hash lleva cada servidor de Discord a su nodo; tuvieron que hacerlo rápido (en inglés)."),
        Ref("libketama: consistent hashing for memcached clients",
            "https://www.metabrew.com/article/libketama-consistent-hashing-algo-memcached-clients",
            "El anillo que copiaron todos los clientes de memcached, de Last.fm (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/consistent_hashing/es/main.py y mira cómo el próximo cambio apenas se nota.",
        "Haz la etapa 2 y mira cómo los nodos naranjas y rojos se vuelven azules.",
        "Prueba --set rate=900: un cambio con módulo lleva la base de datos más allá de su límite.",
    ),
)

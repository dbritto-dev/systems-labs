"""Laboratorio load_balancing, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Balanceo de carga"
SUMMARY = "Un servidor de 8 va lento pero recibe su parte. Reparte por carga, luego con dos al azar."
PARAMS = {"rate": "peticiones de usuarios por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"slow": "LENTO", "fast": "RÁPIDO", "cold": "FRÍO", "warm": "LISTO"}
CAUSES = {
    "noisy_neighbour": "un vecino ruidoso acapara la CPU de su máquina",
    "gc_storm": "una tormenta de recolección de basura: el heap está casi lleno",
    "bad_disk": "su disco está fallando y cada lectura se reintenta",
    "degraded_az": "la red de su zona de disponibilidad está degradada",
    "autoscaler": "el autoescalado lo reemplazó: cachés vacías, el JIT en frío",
    "spot_reclaimed": "reclamaron su instancia spot; la nueva arranca en frío",
    "deploy_restart": "un despliegue gradual lo reinició con las cachés vacías",
}

STAGES = [
    StageText("Por turnos",
              "Reto: un servidor lento sigue recibiendo 1 de cada 8 peticiones; su cola crece: timeouts.",
              "Etapa 1: manda cada petición al servidor con menos en curso"),
    StageText("Menos pendientes",
              "Reto: con informes de carga viejos, todos los balanceadores van en manada al más libre.",
              "Etapa 2: elige dos servidores al azar y manda al menos cargado"),
    StageText("Dos opciones al azar",
              "Resuelto: se evita el servidor lento y las peticiones se reparten, aun con datos viejos.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "pick() debe dar un servidor"),
    "share": GoalText("Serv. lento ≤ 10%", "manda al menos cargado"),
    "p99": GoalText("p99 < 750ms", "2 al azar, el menos cargado"),
    "served": GoalText("Servidas ≥ 99%", "sin manada: dos opciones"),
    "recovered": GoalText("Recuperado ≥ 95%", "vuelve a repartir la carga"),
}

LEGEND = {"idle": "en reposo", "request": "petición", "waits": "espera / cola", "served": "servida",
          "timed_out": "timeout", "server": "servidor", "slow_server": "servidor lento",
          "fair": "reparto justo", "incident": "incidente"}

STRINGS = {
    "note_dots": "Los puntos son una muestra, más lentos (decorativo).",
    # los dibujos
    "topology": "4 balanceadores → 8 servidores",
    "fan_server": "s{n}",
    "fan_slow": "s{n} lento",
    "lanes_balancers": "4 balanceadores",
    "state_sick": "{state} s{server}",
    # incidentes
    "slow_server": "Servidor lento",
    "cold_server": "Servidor en frío",
    "is_slow": "s{server} va {times:.0f}x más lento: {cause}",
    "fast_again": "s{server} vuelve a ir rápido",
    "is_cold": "s{server} reemplazado, {times:.0f}x más lento al principio: {cause}",
    "warm_again": "s{server} ya se ha calentado",
    "warn_timeouts": "{n:.0f} timeouts en un segundo (504)",
    # el panel
    "tile_share": "En lento",
    "tile_served": "Servidas",
    "toplist": "Servidores",
    "bar_busiest": "Más s{n}",
    "bar_quietest": "Menos s{n}",
    "bar_slow": "Lento s{n}",
    "bar_no_slow": "Lento –",
    "limit_fair": "justo {n}/s",
    "head_timeouts": "{n} peticiones con timeout (504)",
    "head_herding": "En manada: {share:.0%} a un servidor",
    "head_full_share": "s{n} va lento y aún recibe {share:.0%}",
    "head_avoided": "s{n} va lento; lo esquivan",
    "head_spread": "Repartidas entre {n} servidores",
    "note_chart": "Gráfica: peticiones/s al servidor lento, y los timeouts.",
    # errores en tu código
    "bad_pick": "pick() devolvió {value}: debe ser el índice de un servidor, de 0 a {last}",
}

LESSON = Lesson(
    title="Balanceo de carga",
    one_liner="Un balanceador que ignora la carga sigue alimentando a un servidor lento. Mandar al menos cargado va en manada con datos viejos; dos opciones al azar, no.",
    learn=(
        "Un balanceador de carga reparte las peticiones entre un grupo de servidores. Por turnos (round "
        "robin) cada servidor recibe el mismo número de peticiones, lo cual es justo solo mientras todos "
        "van igual de rápido.",
        "Los servidores no van igual de rápido mucho tiempo: un vecino ruidoso en la misma máquina, una "
        "tormenta de recolección de basura, un disco que falla, una zona de disponibilidad degradada o un "
        "reemplazo recién arrancado con las cachés vacías. Por turnos se le sigue mandando al lento 1 de "
        "cada 8 peticiones: su cola crece hasta que saltan los timeouts, y el p99 de toda la flota es el de ese servidor.",
        "Menos peticiones pendientes (least outstanding requests) manda cada petición al servidor con menos "
        "en curso, así que el lento, que acumula cola, recibe menos. Pero un balanceador solo conoce la "
        "carga de su último informe, y hay varios balanceadores. Hasta el siguiente informe, todas las "
        "peticiones van al mismo servidor 'libre': en manada. Si ese servidor es el lento, o uno en frío "
        "que acaba de entrar, la manada acaba en timeout.",
        "El poder de dos opciones (power of two choices) elige dos servidores al azar y manda la petición "
        "al menos cargado de los dos. El más ocupado nunca sale elegido, y el resto se reparte el tráfico "
        "en vez de llevárselo todo uno. Mitzenmacher demostró que funciona casi tan bien como el menos "
        "cargado con datos frescos, y mucho mejor con datos viejos.",
        "Los balanceadores reales añaden arranque lento (slow start: subir poco a poco a un servidor nuevo), "
        "detección de atípicos (sacar a un servidor que falla una y otra vez) y timeouts con reintento en "
        "otro servidor.",
    ),
    watch_for=(
        "Por turnos: el servidor lento (morado) recibe toda su parte justa; su cola crece y los usuarios acaban en timeout, en rojo.",
        "Menos pendientes: el lento recibe menos, pero cada medio segundo caen ráfagas enteras sobre un solo servidor.",
        "Dos opciones al azar: el tráfico se reparte entre los servidores sanos y el lento recibe un goteo.",
    ),
    build=(
        ("Envoy: menos peticiones con dos opciones (lo que hace por defecto)",
         "clusters:\n"
         "- name: backend\n"
         "  lb_policy: LEAST_REQUEST\n"
         "  least_request_lb_config:\n"
         "    choice_count: 2"),
        ("NGINX: dos al azar, el que tenga menos conexiones",
         "upstream backend {\n"
         "    random two least_conn;\n"
         "    server 10.0.0.1;\n"
         "    server 10.0.0.2;\n"
         "}"),
        ("HAProxy: el poder de dos opciones al azar",
         "backend app\n"
         "    balance random(2)\n"
         "    server s1 10.0.0.1:8080 check slowstart 30s"),
    ),
    checklist=(
        "Reparte según la carga (peticiones en curso), no solo por turnos: por turnos se alimenta a un servidor lento para siempre.",
        "¿Varios balanceadores, o datos de carga que llegan tarde? Usa dos opciones al azar, no el mínimo global.",
        "Sube poco a poco a los servidores nuevos (slow start), para que a uno en frío no le llegue de golpe su parte entera.",
        "Pon un timeout por petición y saca a los atípicos (servidores que fallan una y otra vez o van mucho más lentos).",
        "Métricas: peticiones y p99 por servidor, peticiones en curso por servidor, timeouts (504) por servidor.",
    ),
    refs=(
        Ref("Mitzenmacher: The Power of Two Choices in Randomized Load Balancing",
            "https://www.eecs.harvard.edu/~michaelm/postscripts/mythesis.pdf",
            "La tesis: dos opciones al azar mejoran a una por un factor exponencial (en inglés)."),
        Ref("Mitzenmacher: How Useful Is Old Information?",
            "https://www.eecs.harvard.edu/~michaelm/postscripts/tpds2000.pdf",
            "Por qué el menos cargado va en manada con datos viejos, y dos opciones no (en inglés)."),
        Ref("Envoy: supported load balancers",
            "https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/load_balancers",
            "Por turnos, menos peticiones con dos opciones, y arranque lento (en inglés)."),
        Ref("Marc Brooker: The power of two random choices",
            "https://brooker.co.za/blog/2012/01/17/two-random.html",
            "Una simulación del mejor de dos frente al menos cargado con datos viejos (en inglés)."),
        Ref("HAProxy: Test driving power of two random choices",
            "https://www.haproxy.com/blog/power-of-two-load-balancing",
            "Medido con muchos balanceadores que comparten un grupo de servidores (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/load_balancing/es/main.py y mira cómo baja la parte del servidor lento, y luego las ráfagas.",
        "Haz la etapa 2 y mira cómo desaparecen las ráfagas y paran los timeouts.",
        "Prueba a elegir tres al azar en vez de dos: ¿mejora, o vuelve a ir en manada?",
    ),
)

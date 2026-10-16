"""Laboratorio broadcast, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Broadcast (Gossip Glomers #3)"
SUMMARY = "Gossip Glomers #3: lleva cada número a los 25 nodos, con particiones y pocos mensajes."
PARAMS = {"rate": "operaciones de clientes por segundo (mitad broadcast, mitad read)"}

INCIDENT = IncidentText("Partición", "la partición", "la próxima partición")
VERBS = {"split": "CORTE", "heal": "UNIDA"}
CAUSES = {
    "tor_switch": "falló un switch top-of-rack",
    "zone_link": "una zona de la nube perdió el enlace con las demás",
    "bgp_flap": "una ruta BGP osciló entre los centros de datos",
    "firewall_rule": "una regla de firewall bloqueó el puerto del clúster en un nodo",
    "bad_nic": "la tarjeta de red de un nodo empezó a perder paquetes",
    "security_group": "un grupo de seguridad mal configurado aisló un nodo",
}

STAGES = [
    StageText("Un solo nodo",
              "Reto: cada nodo solo conoce los números que le envían. Cuéntaselos a los demás.",
              "Etapa 1 (3b): envía los números nuevos a tus vecinos"),
    StageText("Varios nodos",
              "Reto: los números enviados durante una partición no llegan al otro lado. Reintenta.",
              "Etapa 2 (3c): reenvía hasta que el otro nodo confirme"),
    StageText("Tolerante a fallos",
              "Reto: funciona, pero cuesta demasiados mensajes y es lento. Hazlo eficiente.",
              "Etapa 3 (3d): menos de 30 msgs/op, p50 < 400 ms, máx < 600 ms"),
    StageText("Eficiente",
              "Reto: menos de 30 mensajes por operación. Ahora menos de 20: envía por lotes.",
              "Etapa 4 (3e): menos de 20 msgs/op (p50 < 1 s, máx < 2 s)"),
    StageText("Por lotes",
              "Resuelto: cada número llega a cada nodo, con particiones, rápido y con pocos mensajes.",
              "Todas las etapas hechas"),
]

GOALS = {
    "reach": GoalText("Llega a todos", "reenvía los números nuevos"),
    "survive": GoalText("Aguanta corte", "reenvía hasta que confirmen"),
    "msgs30": GoalText("Msgs/op < 30", "envía menos mensajes"),
    "fast": GoalText("Ráp. 400/600", "menos saltos por número"),
    "msgs20": GoalText("Msgs/op < 20", "agrupa los números"),
    "batched": GoalText("Rápido 1s/2s", "envía lotes más a menudo"),
}

LEGEND = {"complete": "tiene todos", "missing": "le faltan", "request": "petición de cliente",
          "message": "mensaje", "dropped": "perdido", "partition": "partición", "limit": "límite"}

STRINGS = {
    # incidentes
    "cut_off": "un nodo queda aislado: {cause}",
    "split": "el clúster se parte en dos: {cause}",
    "whole": "la red vuelve a estar entera",
    "warn_stuck": "{n} números atascados en un lado",
    # valores de los objetivos
    "lost": "perdido",
    # el panel
    "tile_msgs": "Msgs/op",
    "tile_p50": "p50",
    "tile_behind": "Faltan",
    "bar_clients": "Clientes",
    "bar_nodes": "Nodos",
    "limit": "30 msgs/op",
    "chart_limit": "30/op",
    "messages": "Mensajes",
    "head_split": "Corte {sizes}: {n} números esperan",
    "head_behind": "{n} números aún no están en todos los nodos",
    "head_ok": "Cada número en cada nodo (p50 {p50})",
    "note_chart": "Gráfica: mensajes entre nodos por segundo.",
    # errores en tu código
    "no_messages": "BroadcastNode debe guardar los números que tiene en self.messages",
}

LESSON = Lesson(
    title="Broadcast (Gossip Glomers #3)",
    one_liner="Lleva cada número a cada nodo de un clúster, incluso con la red partida, sin inundarla.",
    learn=(
        "Gossip: un nodo que aprende algo nuevo se lo cuenta a sus vecinos, estos a los suyos, y la "
        "noticia llega a todos en pocos saltos. Inundar a todos los vecinos funciona, pero envía el "
        "mismo número por cada enlace.",
        "Particiones: los mensajes que cruzan el corte simplemente se pierden. El gossip de disparar y "
        "olvidar pierde esos números para siempre. Tolerar fallos significa guardar lo que el otro lado "
        "no ha confirmado y enviarlo otra vez hasta que lo confirme (o comparar de vez en cuando lo que "
        "tiene cada lado: anti-entropía).",
        "La eficiencia es un equilibrio: menos saltos (enviar directo a todos, o a través de un hub) "
        "bajan la latencia; agrupar muchos números en un mensaje baja el número de mensajes, a cambio "
        "de esperar al lote.",
        "Las confirmaciones duplican los mensajes. Agrupar también las confirmaciones, y reenviar solo "
        "lo que no se confirmó, mantiene barata la tolerancia a fallos.",
    ),
    watch_for=(
        "Un solo nodo: solo el nodo con el que habló el cliente tiene el número; los demás siguen naranjas.",
        "Varios nodos: los puntos azules se extienden por la cuadrícula; en una partición, puntos rojos mueren en el corte.",
        "Tolerante a fallos: cuando la partición se cura, los números cruzan y los nodos se vuelven azules.",
        "Eficiente y por lotes: muchos menos puntos azules para los mismos números, y siguen llegando rápido.",
    ),
    build=(
        ("Maelstrom: ejecuta el reto real contra tu propio binario",
         "./maelstrom test -w broadcast --bin ./my-broadcast --node-count 25 \\\n"
         "    --time-limit 20 --rate 100 --latency 100 --nemesis partition"),
        ("Reenviar hasta que confirmen (asyncio)",
         "async def push(self, dest, number):\n"
         "    while True:\n"
         "        try:\n"
         "            await self.rpc(dest, {'type': 'gossip', 'message': number}, timeout=0.5)\n"
         "            return\n"
         "        except TimeoutError:\n"
         "            await self.sleep(0.2)"),
    ),
    checklist=(
        "Conoce tu fan-out: mensajes por actualización = nodos a los que llega x (1 + confirmaciones).",
        "Nunca des por hecho que un mensaje llegó: guárdalo hasta que lo confirmen, o repáralo con anti-entropía.",
        "Agrupa en el camino rápido; repara con un temporizador lento.",
        "Mide de punta a punta: el tiempo hasta que cada réplica lo tiene, no solo el primer salto.",
        "Prueba con particiones activadas, siempre.",
    ),
    refs=(
        Ref("Fly.io: Gossip Glomers, challenge #3a Broadcast",
            "https://fly.io/dist-sys/3a/",
            "El reto original y sus partes 3b a 3e (en inglés)."),
        Ref("Maelstrom: the broadcast workload",
            "https://github.com/jepsen-io/maelstrom/blob/main/doc/workloads.md",
            "Los mensajes y lo que mira el comprobador (en inglés)."),
        Ref("Demers et al.: Epidemic algorithms for replicated database maintenance (1987)",
            "https://dl.acm.org/doi/10.1145/41840.41841",
            "De donde vienen el gossip y la anti-entropía (en inglés)."),
        Ref("Amazon Dynamo (2007)",
            "https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf",
            "Gossip para la membresía y anti-entropía con árboles de Merkle en producción (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/broadcast/es/main.py y mira cómo los números se extienden por la cuadrícula.",
        "Luego mira una partición: ¿qué les pasa a los números enviados en el lado pequeño?",
        "Prueba --set rate=60: ¿tus lotes salen más baratos por operación?",
    ),
)

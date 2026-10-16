"""Laboratorio unique_id_generation, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "IDs únicos (Gossip Glomers #1-2)"
SUMMARY = "Gossip Glomers #1-2: echo, y luego IDs únicos en 5 nodos, con particiones y saltos de reloj."
PARAMS = {"rate": "peticiones de clientes por segundo (20% echo, 80% generate)"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"split": "CORTE", "heal": "UNIDA", "clock": "RELOJ", "sync": "AJUSTE", "move": "MUEVE", "back": "VUELVE"}
CAUSES = {
    "switch_failed": "falló un switch de rack",
    "zone_link": "una zona de la nube perdió el enlace con las demás",
    "firewall": "un cambio en el firewall bloqueó el tráfico entre los nodos",
    "ntp_step": "NTP atrasó el reloj después de que el host se adelantara",
    "leap_smear": "el reparto del segundo intercalar se configuró en un solo host",
    "hypervisor_resync": "el hipervisor resincronizó el reloj del invitado tras una pausa",
    "live_migration": "una migración en vivo pausó un nodo; luego NTP le atrasó el reloj",
    "host_drained": "se vació un host por mantenimiento y la VM se movió",
}

STAGES = [
    StageText("Nada aún",
              "Reto: los nodos no responden nada. Empieza con echo: devuelve el mensaje.",
              "Etapa 1 (#1): responde echo_ok con el mismo echo"),
    StageText("Echo",
              "Reto: ahora reparte IDs que ninguna otra petición haya recibido, desde ningún nodo.",
              "Etapa 2 (#2): IDs únicos, sin coordinación"),
    StageText("IDs únicos",
              "Reto: únicos, pero no una clave de 64 bits ordenable. Constrúyelos con el reloj.",
              "Etapa 3: ms | nodo | secuencia, sin ir nunca hacia atrás"),
    StageText("IDs Snowflake",
              "Resuelto: echo funciona y los IDs son únicos, de 64 bits, ordenados y nunca retroceden.",
              "Todas las etapas hechas"),
]

GOALS = {
    "echo": GoalText("Echo funciona", "responde echo_ok"),
    "unique": GoalText("Únicos", "añade el nodo al ID"),
    "available": GoalText("Disponible ≥ 99%", "no preguntes a otros nodos"),
    "compact": GoalText("Enteros 64 bits", "mete el ID en un entero"),
    "ordered": GoalText("Ordenados", "pon primero los milisegundos"),
    "monotonic": GoalText("Nunca atrás", "guarda la última marca"),
}

LEGEND = {"node": "nodo", "clock_back": "reloj atrasado", "duplicate": "dio un duplicado",
          "request": "petición", "reply": "respuesta", "partition": "partición"}

STRINGS = {
    # incidentes
    "title_split": "Partición",
    "title_clock": "Salto de reloj",
    "title_migrate": "Migración",
    "start_split": "los nodos quedan partidos en dos: {cause}",
    "start_clock": "un reloj saltó {seconds:.1f} s atrás: {cause}",
    "start_migrate": "un nodo queda aislado, reloj {seconds:.1f} s atrás: {cause}",
    "end_split": "la red vuelve a estar entera",
    "end_clock": "el reloj vuelve a estar bien",
    "end_migrate": "el nodo vuelve, con el reloj bien",
    # valores de los objetivos
    "none": "ninguno",
    "dups": "{n} dupl.",
    "back": "{n} atrás",
    # el panel
    "tile_dups": "Duplic.",
    "tile_answers": "Resp.",
    "tile_ordered": "Orden",
    "bar_clients": "Clientes",
    "bar_ids": "IDs",
    "requests": "Peticiones",
    "stat_dups": "duplicados",
    "head_dups": "{n} IDs duplicados en los últimos 30 s",
    "head_skew": "el reloj de n{node} va {seconds:.1f} s atrasado",
    "head_split": "Los nodos no se hablan: los IDs no deben necesitarlo",
    "head_ok": "Todos los IDs únicos ({n} IDs/s)",
    "note_chart": "Gráfica: IDs por segundo: únicos, duplicados, fallidos.",
    # el dibujo
    "state_clock": "n{node} RELOJ -{seconds:.1f}s",
    # el dibujo de carriles (lo que ven los clientes): estados bajo el clúster, 13 letras como mucho
    "lanes_dups": "DUPLICADOS",
    "lanes_clock": "DESFASE",
    # el dibujo de pares: bajo un nodo, corto
    "peer_clock": "n{node} reloj −{seconds:g}s",
    "peer_dup": "n{node} ¡duplica!",
}

LESSON = Lesson(
    title="IDs únicos (Gossip Glomers #1-2)",
    one_liner="Reparte IDs que ninguna otra petición haya recibido, desde cualquier nodo, sin preguntar a nadie.",
    learn=(
        "Echo es el hola mundo de un nodo: recibe un mensaje y responde al remitente con in_reply_to puesto.",
        "IDs únicos sin coordinación: combina algo único del nodo (su id) con algo único dentro del nodo "
        "(un contador). No hay mensajes, así que una partición no lo puede parar.",
        "Pedir el siguiente número a un líder o a un contador compartido también da IDs únicos, pero deja "
        "de funcionar cuando la red se parte: es la disponibilidad que pierdes al coordinar.",
        "Una clave de base de datos pide más: un entero de 64 bits que crece con el tiempo, para que las "
        "filas nuevas vayan al final del índice. Snowflake mete milisegundos | nodo | secuencia en 63 bits.",
        "Los relojes saltan hacia atrás (NTP, pausas de la VM, migraciones). Un generador que se fía del "
        "reloj reparte entonces IDs más pequeños, y puede repetir otros viejos. Guarda la última marca de "
        "tiempo que usaste y no bajes nunca de ella.",
    ),
    watch_for=(
        "Nada aún: cada petición vuelve en rojo.",
        "Un contador por nodo: las respuestas se ponen verdes, pero sube la tarjeta Duplic.: n0 y n1 dan 1, 2, 3...",
        "Preguntar a un líder: únicos, hasta que una partición deja nodos sin él y sus peticiones dan timeout.",
        "Nodo + contador: siempre únicos y disponibles, pero son texto y no van ordenados por tiempo.",
        "Snowflake sin protección: cuando un reloj se atrasa (un nodo naranja), sus IDs van hacia atrás.",
    ),
    build=(
        ("IDs Snowflake, protegidos contra relojes que se atrasan",
         "ms = max(wall_ms() - EPOCH_MS, last_ms)\n"
         "seq = seq + 1 if ms == last_ms else 0\n"
         "if seq > 4095:            # gastado este milisegundo\n"
         "    ms, seq = ms + 1, 0\n"
         "last_ms = ms\n"
         "return (ms << 22) | (node << 12) | seq"),
        ("O UUIDv7 (RFC 9562): 48 bits de milisegundos y luego bits al azar, 128 bits",
         "uuid7 = time_ms(48) | version(4) | random(74)   # ordenable, sin números de nodo que asignar"),
    ),
    checklist=(
        "Los IDs salen del propio nodo: ninguna llamada de red en el camino crítico.",
        "Algo único por nodo (un número asignado), más una secuencia por nodo.",
        "Milisegundos primero si los quieres ordenados; una época propia para que 41 bits duren ~69 años.",
        "No dejes nunca que la marca de tiempo retroceda; alerta cuando lo haga el reloj.",
        "Planifica los números de nodo: 10 bits son 1024 generadores, asignados una vez y nunca reutilizados.",
    ),
    refs=(
        Ref("Fly.io: Gossip Glomers #1 Echo", "https://fly.io/dist-sys/1/", "El primer reto (en inglés)."),
        Ref("Fly.io: Gossip Glomers #2 Unique ID Generation", "https://fly.io/dist-sys/2/",
            "IDs únicos que siguen disponibles durante las particiones (en inglés)."),
        Ref("Twitter's Snowflake (2010 source)", "https://github.com/twitter-archive/snowflake/tree/snowflake-2010",
            "El generador original marca | worker | secuencia, y cómo trata los relojes que retroceden (en inglés)."),
        Ref("RFC 9562: UUIDs, including UUIDv7", "https://www.rfc-editor.org/rfc/rfc9562.html",
            "UUIDs ordenados por tiempo, estandarizados (en inglés)."),
        Ref("Google Spanner: TrueTime and external consistency",
            "https://cloud.google.com/spanner/docs/true-time-external-consistency",
            "Lo que cuesta fiarse de los relojes entre máquinas (en inglés)."),
        Ref("Maelstrom workloads (echo, unique-ids)",
            "https://github.com/jepsen-io/maelstrom/blob/main/doc/workloads.md",
            "El banco de pruebas real y sus mensajes (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/unique_id_generation/es/main.py y mira cómo las respuestas se ponen verdes.",
        "Prueba primero un contador por nodo y mira la tarjeta Duplic.: luego arréglalo.",
        "Construye un ID Snowflake que ignore el salto de reloj y espera a un nodo naranja.",
    ),
)

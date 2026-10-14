"""Laboratorio distributed_lock, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Cerrojo distribuido"
SUMMARY = "Los procesos toman un cerrojo antes de escribir un informe compartido. Aguanta dueños congelados, muertos y tardíos."
PARAMS = {"rate": "trabajos por segundo (cada uno toma el cerrojo y escribe el informe)"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"pause": "PAUSA", "wake": "SIGUE", "crash": "CAE", "back": "VUELVE", "delay": "DEMORA",
         "lands": "LLEGA", "cut": "CORTE", "heal": "UNIDO"}
CAUSES = {
    "gc_pause": "una recolección de basura que lo detiene todo, con muchísima memoria",
    "vm_migration": "su máquina virtual se está migrando en vivo a otra máquina",
    "swapping": "su máquina se quedó sin memoria y lo pasó a disco",
    "cpu_throttle": "su contenedor llegó a su límite de CPU y lo frenan",
    "oom_kill": "el kernel lo mató por usar demasiada memoria",
    "kernel_panic": "un kernel panic tras actualizar un controlador",
    "spot_reclaim": "la nube recuperó su instancia spot",
    "bad_deploy": "un despliegue defectuoso lo tumbó",
    "retransmits": "paquetes perdidos: TCP retransmite con backoff",
    "congested_link": "un enlace congestionado hacia el almacenamiento",
    "proxy_queue": "un proxy delante del almacenamiento la dejó en cola",
    "switch_port": "se cayó un puerto del switch hacia el servicio de cerrojos",
    "firewall_rule": "una regla de firewall bloqueó el puerto del servicio de cerrojos",
    "dns": "un cambio de DNS lo mandó a una dirección equivocada del servicio de cerrojos",
}

STAGES = [
    StageText("Cerrojo simple",
              "Reto: el cerrojo nunca caduca: un dueño congelado o muerto bloquea todo. Ponle un plazo.",
              "Etapa 1: un plazo (LEASE) que caduca, renovado por su dueño"),
    StageText("Plazos",
              "Reto: un dueño congelado despierta, cree que aún tiene el cerrojo y escribe. Frénalo.",
              "Etapa 2: tokens de vallado, que comprueba el almacenamiento"),
    StageText("Plazos + tokens de vallado",
              "Resuelto: un dueño muerto bloquea un plazo como mucho, y lo tardío rebota en el almacén.",
              "Todas las etapas hechas"),
]

GOALS = {
    "corrupt": GoalText("Corruptas = 0", "tokens de vallado"),
    "stuck": GoalText("Atasco ≤ 5s", "un plazo que caduque"),
    "done": GoalText("Trabajos hechos ≥ 80%", "renueva; suelta lo perdido"),
}

LEGEND = {"holder": "dueño del cerrojo", "frozen": "congelado", "down": "muerto / aislado",
          "lock_msg": "mensaje del cerrojo", "write": "escritura", "late_write": "escritura demorada",
          "corrupt": "escritura tardía aceptada", "refused": "escritura tardía rechazada"}

STRINGS = {
    # incidentes
    "title_pause": "Pausa",
    "title_crash": "Caída",
    "title_delay": "Escritura tardía",
    "title_partition": "Partición",
    "start_pause": "{worker} se congeló con el cerrojo: {cause}",
    "start_crash": "{worker} murió con el cerrojo: {cause}",
    "start_delay": "una escritura de {worker} se quedó en la red: {cause}",
    "start_partition": "{worker} quedó aislado del servicio de cerrojos: {cause}",
    "end_pause": "{worker} despierta y sigue como si nada",
    "end_crash": "{worker} se reinició",
    "end_delay": "por fin llega la escritura de {worker}",
    "end_partition": "{worker} vuelve a llegar al servicio de cerrojos",
    "warn_corrupt": "una escritura tardía de {worker} (trabajo {job}) pisó datos más nuevos",
    "warn_refused": "el almacenamiento rechazó una escritura tardía de {worker} (trabajo {job})",
    # el panel
    "tile_corrupt": "Corruptas",
    "tile_stuck": "Atasco",
    "tile_done": "Hechos",
    "bar_jobs": "Trabajos",
    "bar_lock": "Cerrojo",
    "bar_writes": "Escrituras",
    "messages": "Mensajes",
    "head_corrupt": "{worker} escribió sin el cerrojo",
    "head_refused": "Rechazada una escritura de {worker}",
    "head_stuck": "Nada hecho en {s:.0f}s: lo tiene {worker}",
    "head_pause": "{worker} congelado con el cerrojo",
    "head_crash": "{worker} murió con el cerrojo",
    "head_delay": "Una escritura de {worker} va tarde",
    "head_partition": "{worker} no llega al cerrojo",
    "head_ok": "Un solo escritor a la vez",
    "note_chart": "Gráfica: mensajes del cerrojo (sondeo mientras está tomado) y escrituras por segundo.",
    # los dibujos: el estado debajo (el de carriles: 13 letras como máximo)
    "state_corrupt": "CORRUPTA",
    "state_refused": "RECHAZADA",
    "state_stuck": "ATASCO {s}s",
    "state_frozen": "{worker} CONGELADO",
    "state_delayed": "DEMORADA",
    "state_lock": "cerrojo: {worker}",
    "nobody": "libre",
}

LESSON = Lesson(
    title="Cerrojo distribuido",
    one_liner="Un cerrojo necesita un plazo, para que un dueño muerto no bloquee para siempre, y un token de vallado, para que uno tardío no escriba.",
    learn=(
        "Un cerrojo distribuido deja que un solo proceso a la vez haga algo: regenerar un informe, ejecutar "
        "una tarea programada una sola vez, ser dueño de un fragmento de los datos. Lo reparte un servicio de cerrojos (ZooKeeper, etcd, "
        "Consul, Redis, una fila de una base de datos).",
        "Un cerrojo que nunca caduca se atasca en cuanto su dueño muere, se congela o pierde la red: nadie "
        "distingue un dueño muerto de uno lento. Por eso los cerrojos tienen un plazo (un lease): el "
        "servicio recupera el cerrojo pasado un TTL, y un dueño que necesita más tiempo lo renueva.",
        "Un plazo no basta. El dueño puede quedarse en pausa más que el TTL (una pausa de recolección de "
        "basura, una migración de máquina virtual, memoria pasada a disco) o su escritura puede quedarse en "
        "la red; mientras, el plazo caduca y otro proceso toma el cerrojo. El primero sigue, seguro de que aún lo tiene, y su "
        "escritura cae encima de datos más nuevos. Mirar el reloj antes de escribir no ayuda: la pausa puede "
        "llegar justo después de mirarlo.",
        "Los tokens de vallado (fencing tokens) lo arreglan donde ocurre el daño. Cada concesión trae un número que solo "
        "crece; el dueño lo envía con cada escritura, y el almacenamiento rechaza una escritura cuyo token "
        "sea más viejo que uno que ya vio. El almacenamiento tiene que participar: un cerrojo solo no puede "
        "frenar una escritura tardía.",
        "'How to do distributed locking', de Martin Kleppmann, lo argumenta contra Redlock: para la "
        "corrección necesitas vallado (y un servicio de cerrojos con consenso); si solo quieres eficiencia "
        "(no hacer dos veces el mismo trabajo), basta un plazo simple.",
    ),
    watch_for=(
        "Cerrojo simple: un dueño congelado pone el cerrojo en rojo; el Atasco sube toda la pausa, y una caída bloquea para siempre.",
        "Plazos: el cerrojo vuelve en ~2 s; pero cuando el proceso congelado despierta, su escritura estalla en rojo junto al almacenamiento.",
        "Plazos + vallado: la misma escritura tardía estalla en naranja: rechazada, porque su token es más viejo.",
        "Escritura tardía: la escritura demorada se arrastra en naranja claro hasta el almacenamiento, mucho después de que su trabajo se rindiera.",
    ),
    build=(
        ("etcd (Go): un plazo, un cerrojo, y su revisión como token de vallado",
         "s, _ := concurrency.NewSession(cli, concurrency.WithTTL(10)) // se renueva mientras vive el proceso\n"
         "m := concurrency.NewMutex(s, \"/locks/report\")\n"
         "if err := m.Lock(ctx); err != nil { return err }\n"
         "token := m.Header().Revision // crece con cada concesión"),
        ("El almacenamiento comprueba el token (SQL)",
         "UPDATE reports SET body = $1, token = $2\n"
         " WHERE id = 7 AND token <= $2;  -- 0 filas: un dueño caducado, recházalo"),
        ("Ejecuta una tarea programada bajo un cerrojo de etcd",
         "etcdctl lock --ttl=10 /locks/nightly-report ./regenerate-report.sh"),
    ),
    checklist=(
        "Decide para qué es el cerrojo: eficiencia (basta un plazo) o corrección (necesitas vallado).",
        "Ponle un TTL a cada cerrojo, renuévalo mientras trabajas y para si falla una renovación.",
        "Reparte un token que solo crezca (revisión de etcd, zxid de ZooKeeper) y envíalo con cada escritura.",
        "Haz que el almacenamiento rechace una escritura con un token más viejo que el último que vio.",
        "Toma el cerrojo de un servicio con consenso (etcd, ZooKeeper), no de un Redis suelto.",
        "Prueba con pausas largas, dueños muertos y redes lentas, no solo con caídas.",
    ),
    refs=(
        Ref("Martin Kleppmann: How to do distributed locking",
            "https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html",
            "Plazos, pausas de recolección de basura y tokens de vallado; por qué Redlock no es seguro para la corrección."),
        Ref("Salvatore Sanfilippo: Is Redlock safe?",
            "http://antirez.com/news/101",
            "La respuesta del autor de Redis: el otro lado del debate."),
        Ref("Redis: cerrojos distribuidos",
            "https://redis.io/docs/latest/develop/use/patterns/distributed-locks/",
            "SET NX PX con un TTL, y el algoritmo Redlock."),
        Ref("Google: The Chubby lock service",
            "https://research.google/pubs/the-chubby-lock-service-for-loosely-coupled-distributed-systems/",
            "Cerrojos de grano grueso con plazos, y secuenciadores: tokens de vallado en producción."),
        Ref("etcd: API (plazos)",
            "https://etcd.io/docs/v3.5/learning/api/",
            "Plazos con TTL, renovaciones y revisiones que solo crecen."),
        Ref("ZooKeeper: recetas (cerrojos)",
            "https://zookeeper.apache.org/doc/current/recipes.html",
            "Cerrojos con nodos efímeros secuenciales, que desaparecen con la sesión."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/distributed_lock/es/main.py y mira cómo el Atasco se queda por debajo de 5 s en la primera pausa.",
        "Mira al proceso congelado despertar al final: ¿dónde cae su escritura?",
        "Haz la etapa 2 y mira la misma escritura estallar en naranja en vez de rojo.",
        "Prueba un LEASE de 0.3 s: ¿qué les pasa a los trabajos que tardan más que su plazo?",
    ),
)

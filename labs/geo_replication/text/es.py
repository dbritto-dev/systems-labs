"""Laboratorio geo_replication, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Replicación geográfica"
SUMMARY = "Un servicio de perfiles en tres regiones, separadas por océanos. Rápido para todos; que aguante perder una región."
PARAMS = {"rate": "operaciones de usuarios por segundo, todas las regiones (20% escrituras)"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"down": "CAÍDA", "up": "VUELVE", "cut": "CORTE", "joined": "UNIDA", "slow": "LENTO", "normal": "NORMAL",
         "peak": "PICO", "calm": "CALMA"}
CAUSES = {
    "power": "un corte de luz apaga sus centros de datos",
    "config_push": "un cambio de configuración erróneo rompe todos los servidores de la región",
    "cloud_outage": "el proveedor de nube tiene una caída regional",
    "cooling": "una falla de refrigeración apaga sus centros de datos",
    "fiber_cut": "un corte de fibra troncal la aísla de las otras regiones",
    "bgp_leak": "una fuga de rutas BGP manda su tráfico entre regiones a ninguna parte",
    "firewall": "una regla nueva de cortafuegos bloquea el tráfico entre regiones",
    "cable_cut": "se corta un cable submarino: el tráfico da un rodeo",
    "congestion": "el enlace se congestiona en las horas pico",
    "reroute": "un proveedor desvía el tráfico por el camino largo",
    "morning": "allí es de mañana: todos abren la aplicación",
    "launch": "un lanzamiento de producto allí",
    "tv_show": "un programa de televisión de allí pide actualizar el perfil",
}

STAGES = [
    StageText("Una región primaria",
              "Reto: quien está lejos cruza un océano en cada lectura; cada escritura vive solo en us.",
              "Etapa 1: una réplica de lectura en cada región"),
    StageText("Réplicas de lectura",
              "Reto: leer es rápido, pero no ven sus propios cambios, y cada escritura tiene una copia.",
              "Etapa 2: escrituras en cada región, dos copias, token de sesión"),
    StageText("Escrituras en cada región",
              "Resuelto: lectura local, un océano por escritura, nada en riesgo, ni al perder una región.",
              "Todas las etapas hechas"),
]

GOALS = {
    "read_p99": GoalText("Lect. p99 ≤ 50ms", "una réplica en cada región"),
    "write_p99": GoalText("Escr. p99 ≤ 0.4s", "confirma con la más cercana"),
    "ryw": GoalText("Lect. viejas = 0", "busca si el token es mayor"),
    "available": GoalText("Éxito ≥ 99%", "escribe en cualquier región"),
    "at_risk": GoalText("En riesgo = 0", "confirma con 2 regiones"),
}

LEGEND = {"fresh": "al día", "behind": "atrasada", "down": "caída", "request": "petición",
          "far": "cruza un océano / lenta", "replication": "replicación", "stale": "no vio lo suyo",
          "failed": "fallida", "limit": "capacidad"}

STRINGS = {
    # incidentes
    "title_down": "Región caída",
    "title_partition": "Aislada",
    "title_slow": "Enlace lento",
    "title_peak": "Pico",
    "down_start": "{name} se apaga: {cause}",
    "down_end": "{name} vuelve; sus usuarios regresan",
    "partition_start": "{name} queda aislada de las otras regiones: {cause}",
    "partition_end": "{name} vuelve a llegar a las otras regiones",
    "slow_start": "enlace {a}–{b} +{ms:.0f} ms, {loss:.0%} perdido: {cause}",
    "slow_end": "el enlace {a}–{b} vuelve a la normalidad",
    "peak_start": "pico en {name}, {x:.1f}x su tráfico: {cause}",
    "peak_end": "terminó el pico de {name}",
    "warn_stale": "un usuario no vio su propia escritura",
    "warn_failed": "{n} operaciones fallaron",
    "warn_risk": "{n} escrituras confirmadas en una sola región",
    # el panel
    "tile_p99": "Lect. p99",
    "tile_stale": "Viejas",
    "tile_available": "Éxito",
    "title": "Regiones",
    "subtitle": "lecturas y escrituras servidas/s, último 1 s",
    "limit": "capacidad {limit:.0f}/s",
    "head_stale": "{n} lecturas sin la escritura del propio usuario en 5 s",
    "head_down": "{name} está caída: sus usuarios van a {to}",
    "head_partition": "{name} está aislada: no llega a las otras",
    "head_slow": "{a}–{b}: +{ms:.0f} ms, {loss:.0%} de mensajes perdidos",
    "head_peak": "pico en {name}, {x:.1f}x: {busiest} al {util:.0%}",
    "head_far": "Los usuarios de {region} esperan {p99} por lectura (p99)",
    "head_ok": "Cada región lee en casa: p99 {p99}",
    "note_nodes": "Columnas: us, eu, ap; filas: sus tres zonas.",
    "note_chart": "Gráfica: operaciones por segundo, por resultado.",
    # el dibujo del clúster: el estado bajo las regiones
    "state_down": "{name} CAÍDA · sus usuarios → {to}",
    "state_partition": "{name} AISLADA",
    "state_slow": "ENLACE {a}–{b} +{ms:.0f} ms",
    "state_peak": "PICO EN {name} {x:.1f}x",
    "state_ok": "TODAS LAS REGIONES ARRIBA · lectura p99 {p99}",
    "state_stale": "{n} SIN LO PROPIO",
    # el dibujo de carriles: estados bajo el servidor, 13 letras como mucho
    "lanes_stale": "DATOS VIEJOS",
    "lanes_down": "{name} CAÍDA",
    "lanes_cut": "{name} AISLADA",
    "lanes_busy": "{name} AL {util:.0%}",
    "lanes_far": "p99 {p99}",
    # el dibujo de pares: bajo cada región, corto; en cada enlace, su latencia de ida
    "peer_behind": "{name}\n−{n}",
    "peer_ms": "{ms:.0f}ms",
    "peer_ms_way": "{ms:.0f}ms de ida",
    "note_regions": "En cada enlace: su latencia de ida.",
    # errores en tu código
    "no_store": "RegionNode debe guardar sus datos en self.store, como {key: (version, value)}: el comprobador mira ahí",
}

LESSON = Lesson(
    title="Replicación geográfica",
    one_liner="Pon una copia en cada región para leer rápido; confirma una escritura cuando dos regiones la "
              "tienen; deja que el token de sesión mantenga visibles las escrituras de cada usuario, caiga donde caiga.",
    learn=(
        "La luz en la fibra tarda ~70 ms en cruzar el Atlántico y ~100-150 ms en cruzar el Pacífico, solo de ida. "
        "Un servicio con una sola región primaria hace que cada usuario lejano pague un viaje de ida y vuelta "
        "por petición, y cuando esa región cae (un corte de luz, un cambio de configuración erróneo, una caída "
        "de la nube) todo se detiene: lecturas y escrituras, en todas partes.",
        "Las réplicas de lectura en cada región hacen locales las lecturas. El primario sigue recibiendo cada "
        "escritura y la envía a las réplicas de forma asíncrona: llega decenas o cientos de milisegundos después. "
        "Un usuario en Europa que guarda un ajuste y recarga puede leer la réplica antes de que llegue el cambio "
        "(no lee sus propias escrituras). Las últimas escrituras del primario existen en una sola región: si se "
        "pierde, se pierden con ella (RPO > 0). Y con el primario caído, nadie puede escribir.",
        "Escribir en cada región elimina el punto único de falla. Aquí el perfil de cada usuario solo lo escribe "
        "su dueño, una petición a la vez, así que los conflictos son raros: gana la versión más nueva (gana el "
        "último que escribe). Confirma una escritura solo cuando una segunda región también la tiene, la primera "
        "de las otras dos en responder: un océano por escritura, nunca dos, y ninguna escritura confirmada vive "
        "en una sola región. Ese es el precio de RPO = 0: ~140-300 ms por escritura, con lecturas locales.",
        "El failover es una regla, no una esperanza: el balanceador manda a los usuarios de una "
        "región caída a la siguiente, que acepta sus escrituras. La aplicación también reintenta en otra región "
        "y evita unos segundos la que le falló, así que las peticiones de un usuario pueden caer en regiones "
        "distintas. El token de sesión (la versión más nueva que el usuario escribió o vio) le dice a cualquier "
        "región si su copia es lo bastante nueva; si no, busca la nueva en otra región, o se niega y la "
        "aplicación reintenta. Una región que estuvo caída o aislada se pone al día con pistas: las escrituras "
        "que se perdió, reenviadas hasta que las confirme.",
    ),
    watch_for=(
        "Una primaria: puntos naranjas cruzan de eu y ap a us en cada petición; cuando us queda aislada, "
        "mueren a mitad de camino y las aplicaciones reintentan en us; cuando us se pone roja, toda petición falla.",
        "Réplicas de lectura: las lecturas se quedan en su columna; lotes azules cruzan a las réplicas; "
        "respuestas moradas cuando un usuario lee antes de que llegue su escritura; con us caída, escribir falla.",
        "Escrituras en todas partes: cada escritura manda dos puntos azules y se responde con la primera "
        "respuesta; los usuarios de una región aislada escriben en otra, y su columna se pone naranja "
        "(atrasada) hasta que llegan las pistas.",
        "Escrituras en riesgo: se cuentan cada 0.2 s mirando dentro de cada región. La replicación asíncrona "
        "siempre tiene alguna.",
    ),
    build=(
        ("Confirma tras una segunda región (asyncio)",
         "self.keep(key, version, value)\n"
         "tasks = [asyncio.ensure_future(self.send_to(r, key, version, value)) for r in nearest(region)]\n"
         "for done in asyncio.as_completed(tasks):\n"
         "    if await done:\n"
         "        return True   # dos regiones la tienen: se puede confirmar\n"
         "return False          # solo aquí: responde un error, la aplicación reintenta en otra"),
        ("Un token de sesión en las lecturas",
         "version, value = self.store.get(key, (0, None))\n"
         "if version < token:            # este usuario escribió o vio algo más nuevo\n"
         "    found = await self.fetch(key, token)\n"
         "    if found is None:\n"
         "        return error(11)       # nunca respondas algo más viejo que su propia escritura\n"
         "    version, value = found"),
        ("CockroachDB: sobrevivir a la pérdida de una región",
         "ALTER DATABASE profiles SET PRIMARY REGION \"us-east1\";\n"
         "ALTER DATABASE profiles ADD REGION \"europe-west1\";\n"
         "ALTER DATABASE profiles ADD REGION \"asia-northeast1\";\n"
         "ALTER DATABASE profiles SURVIVE REGION FAILURE;\n"
         "ALTER TABLE users SET LOCALITY REGIONAL BY ROW;  -- cada fila vive donde vive su usuario"),
    ),
    checklist=(
        "Mide el p99 por región, no global: el promedio esconde a los usuarios al otro lado del océano.",
        "Sirve las lecturas desde una copia en la región del usuario; manda por los océanos solo las escrituras.",
        "Decide tu RPO: confirma una escritura cuando una segunda región la tiene si perder una región no debe "
        "perder nada.",
        "Espera a la primera de las otras regiones, no a todas: una región caída no debe detener las escrituras.",
        "Dale a cada petición un token de sesión, y nunca respondas algo más viejo.",
        "Escribe la regla de failover: quién recibe a los usuarios de una región caída, y sus "
        "escrituras.",
        "Devuelve los usuarios a su región solo cuando se puso al día, o deja que los tokens lo detecten.",
        "Resuelve los conflictos a propósito (solo escribe el dueño, gana la más nueva, o CRDT), y pruébalo con "
        "una partición.",
    ),
    refs=(
        Ref("AWS: Disaster recovery options in the cloud",
            "https://docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws/"
            "disaster-recovery-options-in-the-cloud.html",
            "Copia y restauración, luz piloto, espera semiactiva, activo/activo en varios sitios: RPO y RTO."),
        Ref("Azure Cosmos DB: Niveles de coherencia",
            "https://learn.microsoft.com/es-es/azure/cosmos-db/consistency-levels",
            "Coherencia de sesión: leer tus escrituras con tokens de sesión, entre regiones."),
        Ref("Amazon DynamoDB global tables",
            "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GlobalTables.html",
            "Escrituras en varias regiones, gana el último que escribe, y qué pierde la caída de una región."),
        Ref("CockroachDB: Multi-region survival goals",
            "https://www.cockroachlabs.com/docs/stable/multiregion-survival-goals",
            "Sobrevivir a una zona o a una región, y la latencia de escritura que cuesta cada una."),
        Ref("AWS: Disaster recovery architecture, part IV: multi-site active/active",
            "https://aws.amazon.com/blogs/architecture/disaster-recovery-dr-architecture-on-aws-part-iv-multi-site-active-active/",
            "Usuarios atendidos desde todas las regiones a la vez, y cómo moverlos cuando una falla."),
        Ref("Terry et al.: Session guarantees for weakly consistent replicated data (1994)",
            "https://www.cs.cornell.edu/courses/cs734/2000FA/cached%20papers/SessionGuaranteesPDIS_1.html",
            "Leer tus escrituras y lecturas monótonas, con estado de sesión, mientras los clientes cambian de servidor."),
        Ref("Amazon Route 53: DNS failover",
            "https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/dns-failover.html",
            "Chequeos de salud, enrutamiento con failover, y por qué las cachés de DNS la hacen gradual."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/geo_replication/es/main.py y mira bajar el p99 de lectura en eu y ap.",
        "Luego mira a us quedar aislada: los usuarios no ven sus escrituras. Haz la etapa 2 y mira a los "
        "tokens detectarlo.",
        "Prueba --set rate=300: las regiones se acercan a su capacidad durante un pico.",
    ),
)

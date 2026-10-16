"""Laboratorio caching, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Estampida en la caché"
SUMMARY = "Cada lectura espera a una base de datos lenta. Guarda las claves calientes y sobrevive a un vaciado."
PARAMS = {"rate": "páginas por segundo (cada página lee 3 claves)", "ttl": "segundos que vive un valor en la caché"}

INCIDENT = IncidentText("Vaciado", "el vaciado", "el próximo vaciado")
VERBS = {"flush": "VACÍA", "end": ""}
CAUSES = {
    "deploy_restart": "un despliegue reinició los nodos de la caché",
    "config_roll": "un cambio de configuración reinició el clúster de la caché",
    "out_of_memory": "la caché se quedó sin memoria y se reinició",
    "kernel_update": "una actualización del kernel reinició los servidores de la caché",
    "empty_replica": "la caché conmutó a una réplica vacía",
    "cold_node": "un corte de red hizo que el cliente se reconectara a un nodo frío",
}

STAGES = [
    StageText("Sin caché",
              "Reto: cada lectura espera a la base de datos. Guarda en memoria las claves calientes.",
              "Etapa 1: cache-aside con un TTL"),
    StageText("Cache-aside",
              "Reto: tras un vaciado, los fallos van juntos a la base de datos. Carga cada clave una vez.",
              "Etapa 2: cargas single-flight y TTL con jitter"),
    StageText("A prueba de estampidas",
              "Resuelto: las claves calientes salen de memoria y tras un vaciado cada una carga una vez.",
              "Las dos etapas hechas"),
]

GOALS = {
    "hits": GoalText("Aciertos ≥ 80%", "añade cache-aside con TTL"),
    "dups": GoalText("Dobles < 5%", "single-flight en get()"),
    "p99": GoalText("p99 < 200ms", "carga cada clave una vez"),
}

LEGEND = {"idle": "en reposo", "hit": "acierto", "shared": "espera una carga", "first": "primera carga",
          "dup": "carga duplicada", "rejected": "rechazada", "limit": "límite", "flush": "tras un vaciado"}

STRINGS = {
    # el dibujo de clúster: clientes -> app -> caché (derecha) y base de datos (abajo)
    "pic_state": "app · caché · base de datos: {state}",
    "pic_empty": "app · caché VACÍA · base de datos: {state}",
    # el dibujo de relevo: la caché entre la puerta y la base de datos, su acierto en el último segundo
    "relay_cache": "caché {hits:.0%} acierto",
    "relay_flushed": "vaciada {hits:.0%} acierto",
    # incidentes
    "flushed": "está vacía: {cause}",
    "warn_db": "lecturas de la base de datos {ratio:.1f}x lo normal",
    # valores de los objetivos
    "failed": "fallido",
    # el panel
    "tile_hits": "Acierto",
    "tile_dups": "Dobles",
    "tile_p99": "p99",
    "toplist": "Lecturas",
    "bar_users": "Usuarios",
    "bar_db": "BD",
    "limit": "límite {limit:.0f}/s",
    "head_hit_db": "Vaciado: {ratio:.0f}x lecturas van a la base de datos",
    "head_refilling": "Vaciado: la caché se está llenando",
    "head_no_cache": "Sin caché: cada lectura va a la base de datos",
    "head_cache": "Caché: {share:.0%} de las lecturas desde memoria",
    "note_dots": "Los puntos son una muestra de lecturas, más lentas (decorativo).",
    "note_chart": "Gráfica: lecturas de la base de datos por segundo.",
    # errores en tu código
    "stuck": "una lectura lleva más de {seconds:.0f} s: ¿get() espera algo que nunca termina?",
}

LESSON = Lesson(
    title="Estampida en la caché",
    one_liner="Una caché esconde una base de datos lenta, hasta que se vacía y cada fallo va a la base de datos a la vez.",
    learn=(
        "Cache-aside: lee la caché; si falla, lee la base de datos, guarda el valor con un TTL y "
        "devuélvelo. Con tráfico sesgado (unas pocas claves calientes) casi todas las lecturas salen de memoria.",
        "Un vaciado (un despliegue, un reinicio, un failover) deja la caché vacía. Ahora cada lectura "
        "falla. Una clave caliente se lee muchas veces mientras su primera carga sigue en curso, y cada uno "
        "de esos fallos lanza su propia carga: una estampida (thundering herd).",
        "Las cargas duplicadas hacen cola en la base de datos, así que cada carga tarda más, y todavía más "
        "lecturas fallan mientras tanto. Las claves calientes caras (una portada, un top 10) lo empeoran.",
        "Single-flight: el primer fallo de una clave lanza la carga; los demás esperan a esa misma carga. "
        "Una lectura de la base de datos por clave, haya los lectores que haya.",
        "TTL con jitter: las claves cargadas juntas tras un vaciado también caducarían juntas. Un TTL al "
        "azar (digamos ±20%) reparte las caducidades.",
    ),
    watch_for=(
        "Sin caché: 'Usuarios' supera el límite de la base de datos, la cola se llena y las lecturas esperan o fallan.",
        "Cache-aside: todo tranquilo hasta un vaciado; luego cargas duplicadas naranja oscuro y un p99 cerca de un segundo.",
        "A prueba de estampidas: tras un vaciado la base de datos trabaja más un rato, pero cada clave carga una vez.",
        "Single-flight no reduce los fallos de claves distintas; elimina los duplicados.",
    ),
    build=(
        ("Go: golang.org/x/sync/singleflight",
         "v, err, _ := group.Do(key, func() (any, error) {\n"
         "    return db.Load(ctx, key)\n"
         "})"),
        ("Python asyncio: un future por clave en curso",
         "if (fut := self.loading.get(key)) is not None:\n"
         "    return await asyncio.shield(fut)\n"
         "fut = self.loading[key] = loop.create_future()\n"
         "try:\n"
         "    fut.set_result(value := await db.read(key))\n"
         "    return value\n"
         "except BaseException as e:  # si falla la carga, falla a todos los que esperan; no los cuelga\n"
         "    fut.set_exception(e)\n"
         "    raise\n"
         "finally:\n"
         "    del self.loading[key]"),
        ("TTL con jitter (Redis)",
         "ttl = int(BASE_TTL * random.uniform(0.8, 1.2))\n"
         "await redis.set(key, value, ex=ttl)"),
    ),
    checklist=(
        "Conoce tu tasa de aciertos y qué hace la base de datos al 0% (tras un vaciado o un arranque en frío).",
        "Single-flight (o concesiones, leases) por clave en la ruta de lectura, al menos por proceso.",
        "TTL con jitter, y refresca pronto las claves calientes (caducidad anticipada probabilística) en vez de dejarlas caducar.",
        "Calienta la caché antes de que un despliegue reciba tráfico, o despliega poco a poco.",
        "Protege igualmente la base de datos: una cola acotada, timeouts y descarte de carga.",
    ),
    refs=(
        Ref("AWS: Caching best practices",
            "https://aws.amazon.com/caching/best-practices/",
            "Cache-aside (carga perezosa), TTL y el thundering herd (en inglés)."),
        Ref("Scaling Memcache at Facebook (NSDI 2013)",
            "https://www.usenix.org/conference/nsdi13/technical-sessions/presentation/nishtala",
            "Concesiones (leases): un cliente recarga una clave, los demás esperan o usan un valor viejo (en inglés)."),
        Ref("Go: singleflight",
            "https://pkg.go.dev/golang.org/x/sync/singleflight",
            "Supresión de llamadas duplicadas en pocas líneas (en inglés)."),
        Ref("Optimal Probabilistic Cache Stampede Prevention (VLDB 2015)",
            "https://www.vldb.org/pvldb/vol8/p886-vattani.pdf",
            "XFetch: refresca una clave antes, con una probabilidad que crece al acercarse su caducidad (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/caching/es/main.py y mira cómo sube la tasa de aciertos; luego espera un vaciado.",
        "Haz la etapa 2 y mira cómo desaparece el naranja oscuro tras el siguiente vaciado.",
        "Prueba --set ttl=5 y --set ttl=120: ¿qué pasa con la tasa de aciertos y con cada vaciado?",
    ),
)

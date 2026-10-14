"""Laboratorio cache_invalidation, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Invalidación de caché"
SUMMARY = "Los precios cambian mientras miles los leen de una caché. Nunca sirvas ni guardes uno viejo."
PARAMS = {"rate": "páginas vistas por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"campaign": "PRECIO", "import": "CARGA", "slow": "LENTO", "restart": "CAÍDA", "calm": "CALMA"}
CAUSES = {
    "flash_prices": "una campaña de ofertas cambia el precio de los productos populares",
    "repricing_bot": "un robot de precios sigue los precios de la competencia",
    "currency": "un cambio de divisa recalcula el precio de los más vendidos",
    "black_friday": "entran en vigor los precios del Black Friday en los productos populares",
    "supplier_feed": "se importa de golpe el catálogo del proveedor",
    "catalog_sync": "la sincronización nocturna del catálogo se ejecuta a mediodía",
    "erp_export": "el ERP envía una exportación completa del inventario",
    "cross_az": "los servidores pasan a otra zona, lejos de la caché y de la base de datos",
    "packet_loss": "un switch averiado pierde paquetes; cada ida y vuelta se retransmite",
    "noisy_neighbour": "un vecino ruidoso satura la red de las máquinas",
    "oom_kill": "el sistema mata el nodo de caché por usar demasiada memoria",
    "kernel_update": "el nodo de caché se reinicia por un parche del kernel",
    "cache_deploy": "se despliega una versión nueva de la caché",
}

STAGES = [
    StageText("Caché, luego base de datos",
              "Reto: la caché muestra precios que la BD rechazó. Escribe la BD y luego borra la clave.",
              "Etapa 1: escribe primero la base de datos y luego borra la clave"),
    StageText("Escribir y luego borrar",
              "Reto: un lector lento repone un precio viejo tras el borrado. Rellena con concesión.",
              "Etapa 2: lease_get al fallar, lease_set al rellenar; TTL de 30 s"),
    StageText("Rellenos con concesión",
              "Resuelto: no se sirve ni se guarda ningún precio viejo, y la caché sigue atendiendo.",
              "Todas las etapas hechas"),
]

GOALS = {
    "hits": GoalText("Aciertos ≥ 85%", "guarda en caché lo que lees"),
    "phantom": GoalText("No guardados = 0", "escribe la BD, luego borra"),
    "stale": GoalText("Lect. viejas = 0", "rellena con concesión"),
    "entries": GoalText("Claves viejas = 0", "rechaza rellenos tardíos"),
    "db": GoalText("Lect. BD ≤ 500/s", "rellena la caché al fallar"),
}

LEGEND = {"idle": "en reposo", "hit": "acierto", "miss": "fallo: lee la BD", "stale": "lectura vieja",
          "served": "al día", "write": "escritura, borrado", "refused": "relleno rechazado",
          "incident": "incidente"}

STRINGS = {
    # incidentes
    "campaign_start": "{rate:.0f} escrituras de precio/s en los productos populares, dos por producto: {cause}",
    "campaign_end": "la campaña ha terminado",
    "import_start": "{rate:.0f} escrituras/s en todo el catálogo: {cause}",
    "import_end": "la carga ha terminado",
    "slow_start": "cada ida y vuelta tarda {times:.0f} veces más: {cause}",
    "slow_end": "la red vuelve a ir rápido",
    "restart_start": "el nodo de caché no responde y vuelve vacío: {cause}",
    "restart_end": "el nodo de caché ha vuelto, vacío",
    "warn_stale": "{n} lecturas viejas servidas",
    "warn_phantom": "{n} lecturas sirvieron un precio que nunca se guardó",
    # valores de los objetivos
    "count": "{n}",
    "per_s": "{n:.0f}/s",
    # el panel
    "tile_stale": "Viejas",
    "tile_hits": "Acierto",
    "tile_keys": "Claves",
    "bar_reads": "Lecturas",
    "bar_db": "Lect. BD",
    "bar_writes": "Escrit.",
    "limit": "lecturas BD/s",
    "head_stale": "{n} lecturas viejas en 10 s",
    "head_keys": "{n} claves viejas en la caché",
    "head_campaign": "Campaña: cambian precios populares",
    "head_import": "Carga: se reescribe el catálogo",
    "head_slow": "Red lenta: más hueco para colarse",
    "head_restart": "Caché reiniciada: todo va a la BD",
    "head_ok": "Toda lectura está al día",
    # los dibujos
    "state_stale": "{n} CLAVES VIEJAS",
    "state_down": "CACHÉ CAÍDA",
    "state_slow": "RED LENTA",
    "state_writes": "MUCHAS ESCRITURAS",
    "pic_state": "3 servidores, caché, BD: {state}",
    "note": "Los puntos son una muestra de lecturas y escrituras, más lentas (estético).",
    "subtitle": "por segundo, último 1 s",
    "title": "Lecturas, escrituras",
    # errores en tu código
    "stuck": "una petición lleva más de {seconds:.0f} s: ¿read() y update() llegan a devolver algo?",
    "bad_read": "read() devolvió {value}, no un registro de la caché o de la base de datos",
}

LESSON = Lesson(
    title="Invalidación de caché",
    one_liner="Una caché delante de una base de datos es una segunda copia de los datos; cada escritura "
              "tiene que arreglarla, y cada lector lento puede volver a estropearla.",
    learn=(
        "Si escribes primero la caché y después la base de datos, fallan dos cosas. Cuando la base de "
        "datos rechaza la escritura (un timeout de bloqueo, una restricción), la caché sirve un precio "
        "que nunca se guardó. Cuando dos escrituras se solapan, la caché puede quedarse con el valor de "
        "una y la base de datos con el de la otra. Cualquiera de los dos dura hasta que vence el TTL.",
        "Cache-aside (cargar al fallar) arregla el orden: escribe la base de datos y luego borra la clave (no la "
        "actualices). Una escritura fallida no toca la caché; un borrado no compite con el valor de otra "
        "escritura, y el siguiente lector carga la verdad.",
        "Queda una carrera. Un lector falla, lee la base de datos (el precio viejo) y se detiene: una "
        "pausa del recolector de basura, una respuesta lenta. Mientras tanto, otra escritura se "
        "consolida y borra la clave. Entonces el lector guarda lo que leyó: el precio viejo, después del "
        "borrado, durante todo el TTL. Nadie lo volverá a borrar hasta la próxima escritura.",
        "Las concesiones (leases, del memcache de Facebook, 2013) la cierran. Un fallo le da al lector un token; "
        "borrar la clave anula todos los tokens emitidos para ella; la caché rechaza un relleno cuyo "
        "token ya no vale. Un relleno tardío y viejo simplemente se descarta, y el siguiente lector "
        "carga el precio nuevo. Un número de versión hace lo mismo: la caché recuerda la versión más "
        "nueva que ha visto (incluso tras un borrado) y rechaza una más vieja.",
        "Mantén un TTL de todos modos, lo bastante corto para acotar el daño de lo que no hayas "
        "previsto: un borrado perdido en un corte de red, un error en un escritor. Es una red de "
        "seguridad, no la forma de estar al día.",
    ),
    watch_for=(
        "Caché, luego base de datos: durante la campaña de precios, lecturas rojas en la puerta: precios "
        "que la base de datos rechazó, y precios viejos.",
        "Escribir y luego borrar: ningún precio sin guardar, pero en el dibujo del clúster los rellenos "
        "rojos reponen precios viejos tras un borrado, y los lectores los reciben durante minutos.",
        "Rellenos con concesión: esos rellenos tardíos se rechazan (naranja); las lecturas y claves viejas "
        "se quedan en 0.",
    ),
    build=(
        ("Python: escrituras con cache-aside",
         "async def update(key, record):\n"
         "    await db.write(key, record)      # si lanza un error, la caché no se toca\n"
         "    await cache.delete(key)          # el siguiente lector carga el registro nuevo"),
        ("Python: rellenos con concesión",
         "lease = await cache.lease_get(key)\n"
         "if lease.value is not None:\n"
         "    return lease.value\n"
         "record = await db.read(key)\n"
         "await cache.lease_set(key, record, lease.token, ttl=30)  # se rechaza tras un borrado\n"
         "return record"),
        ("Redis: un relleno con versión (Lua, atómico)",
         "-- KEYS[1] = clave, ARGV = valor, versión, ttl; quien escribe sube 'ver:'..clave en cada escritura\n"
         "if tonumber(redis.call('GET', 'ver:'..KEYS[1]) or 0) > tonumber(ARGV[2]) then return 0 end\n"
         "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[3]) return 1"),
    ),
    checklist=(
        "Quien escribe cambia primero la base de datos y después invalida la caché; nunca al revés.",
        "Invalida con un borrado, no con un set: un set compite con otras escrituras.",
        "Los rellenos tras un fallo son condicionales: un token de concesión o una versión, para que un "
        "relleno tardío no deshaga un borrado.",
        "Cada entrada de la caché tiene un TTL, lo bastante corto para que una invalidación perdida se "
        "cure sola.",
        "Cuenta las lecturas viejas (compara una clave en la caché y en la base de datos) y alerta con ellas.",
        "Vigila los aciertos y las lecturas de la base de datos tras reiniciar la caché.",
    ),
    refs=(
        Ref("Nishtala et al.: Scaling Memcache at Facebook (NSDI 2013)",
            "https://www.usenix.org/conference/nsdi13/technical-sessions/presentation/nishtala",
            "Concesiones (leases) contra rellenos viejos y avalanchas de fallos, sección 3.2.1 (en inglés)."),
        Ref("Microsoft: patrón Cache-Aside",
            "https://learn.microsoft.com/es-es/azure/architecture/patterns/cache-aside",
            "Cargar al fallar, invalidar al escribir, y por qué la caché aún puede quedar incoherente."),
        Ref("AWS: buenas prácticas de caché",
            "https://aws.amazon.com/caching/best-practices/",
            "Carga diferida, escritura directa y TTL (en inglés)."),
        Ref("Redis: caché en el cliente",
            "https://redis.io/docs/latest/develop/reference/client-side-caching/",
            "Mensajes de invalidación, y la carrera entre una lectura y una invalidación (en inglés)."),
        Ref("Martin Fowler: Two hard things",
            "https://martinfowler.com/bliki/TwoHardThings.html",
            "«Solo hay dos cosas difíciles en informática: invalidar cachés y poner nombres» (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/cache_invalidation/es/main.py y mira cómo desaparecen los precios sin guardar.",
        "Luego cambia al dibujo del clúster (v) durante una campaña y busca rellenos rojos.",
        "Haz la etapa 2 y mira cómo esos rellenos tardíos se vuelven naranjas: rechazados.",
    ),
)

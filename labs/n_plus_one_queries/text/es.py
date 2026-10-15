"""Laboratorio n_plus_one_queries, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Consultas N+1"
SUMMARY = "Una página consulta la base de datos una vez por elemento. Agrúpalas y luego usa un JOIN."
PARAMS = {"rate": "páginas abiertas por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"slow": "LENTA", "fast": "RÁPIDA", "big": "LARGAS", "normal": "NORMAL", "spike": "PICO", "calm": "CALMA"}
CAUSES = {
    "backup": "una copia de seguridad nocturna lee todas las tablas",
    "noisy_disk": "un vecino ruidoso satura el disco",
    "zone_failover": "la primaria pasó a otra zona",
    "vacuum": "un vacuum largo corre sobre la tabla de pedidos",
    "flash_sale": "unas rebajas relámpago: cada tienda tiene muchos más pedidos",
    "bulk_import": "un comercio importó sus pedidos de golpe",
    "holiday_orders": "temporada de fiestas: las listas de pedidos son largas",
    "newsletter": "acaba de salir el boletín",
    "tv_ad": "un anuncio de televisión mandó a todos a la web",
    "bot_crawl": "un bot de un buscador recorre todas las páginas",
}

STAGES = [
    StageText("N+1",
              "Reto: cada página manda una consulta por pedido. Trae sus clientes en una sola consulta.",
              "Etapa 1: un fetch_customers(ids) por página (IN)"),
    StageText("Agrupadas",
              "Reto: 2 viajes por página; si la base de datos va lenta, las páginas se arrastran. Únelas.",
              "Etapa 2: un fetch_orders_with_customers por página (JOIN)"),
    StageText("Con JOIN",
              "Resuelto: una consulta por página; una BD lenta cuesta un viaje, no docenas.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "load_page debe dar filas"),
    "queries": GoalText("Consultas/pág ≤ 2", "clientes en un solo IN"),
    "busy": GoalText("BD ocupada < 90%", "manda menos consultas"),
    "p99": GoalText("p99 página < 40ms", "un JOIN: un solo viaje"),
    "served": GoalText("Servidas ≥ 99%", "las páginas deben funcionar"),
}

LEGEND = {"idle": "en reposo", "list": "consulta de lista", "per_item": "una por pedido", "batch": "lote IN",
          "join": "join", "served": "servida", "failed": "abandonada", "incident": "incidente"}

STRINGS = {
    # incidentes
    "title_slow_db": "BD lenta",
    "title_big_pages": "Páginas largas",
    "title_spike": "Pico",
    "slow_db": "va lenta, +{ms:.0f} ms por viaje: {cause}",
    "slow_db_end": "vuelve a ir rápida",
    "big_pages": "las páginas son {times:.0f}x más largas: {cause}",
    "big_pages_end": "las páginas vuelven a lo normal",
    "spike": "recibe {times:.0f}x páginas: {cause}",
    "spike_end": "el tráfico vuelve a lo normal",
    "warn_busy": "base de datos ocupada al {busy:.0%}",
    # el panel
    "tile_queries": "Cons/pág",
    "tile_p99": "p99",
    "tile_busy": "BD ocup.",
    "toplist": "Consultas",
    "bar_pages": "Páginas",
    "bar_queries": "Consultas",
    "head_slow": "BD lenta: {qpp:.1f} consultas por página, p99 {p99}",
    "head_busy": "BD al {busy:.0%}: las páginas esperan",
    "head_calm": "{qpp:.1f} consultas por página",
    "note": "Puntos: consultas de 1 de cada 4 páginas (velocidad estética).",
    # el dibujo de clúster: la topología bajo la cuadrícula
    "pic_state": "app → BD · {qpp:.1f} consultas/página: {state}",
    # el dibujo de relevo: las palabras bajo la app
    "relay_app": "app {qpp:.1f} cons/pág",
    # errores en tu código
    "stuck": "una página lleva más de {seconds:.0f} s cargando: ¿load_page espera sin fin?",
}

LESSON = Lesson(
    title="Consultas N+1",
    one_liner="Una página que consulta la base de datos una vez por elemento hace N+1 viajes; agrúpalos o únelos en uno o dos.",
    learn=(
        "El problema N+1: cargas una lista (1 consulta) y luego, para cada uno de sus N elementos, algo "
        "relacionado (N consultas). En el código parece inofensivo (acceder a un atributo del ORM en un "
        "bucle) y en una base de datos de desarrollo tranquila, donde un viaje cuesta una fracción de "
        "milisegundo.",
        "En producción cada consulta es un viaje de ida y vuelta: la red, una conexión del pool, el "
        "trabajo de la propia base de datos. 30 páginas/s con 20 elementos son 630 consultas/s donde "
        "bastarían 60; cuando la base de datos se ralentiza, cada uno de esos viajes se ralentiza y las "
        "páginas dan timeout.",
        "Agrupar: junta los ids y pregunta una vez (WHERE id IN (...)): 2 consultas por página, sea cual "
        "sea N. Los ORM lo llaman carga anticipada: prefetch_related en Django, includes en Rails, "
        "selectinload en SQLAlchemy.",
        "Unir: deja que la base de datos junte pedidos y clientes en una consulta (select_related en "
        "Django, un JOIN): 1 viaje por página. Importa sobre todo cuando los viajes son lentos.",
        "Lanzar las N consultas a la vez (asyncio.gather) esconde un poco la latencia pero manda las "
        "mismas consultas: la base de datos se sigue ahogando.",
    ),
    watch_for=(
        "N+1: puntos naranja intenso, ~21 consultas por página; con la BD lenta se llenan sus 8 conexiones.",
        "Agrupadas: 2 consultas por página y la BD casi parada, pero cada página necesita 2 viajes lentos.",
        "Con JOIN: 1 consulta por página; aunque la BD vaya lenta, una página tarda un solo viaje.",
        "Las páginas largas (unas rebajas) castigan más al N+1: las consultas crecen con la lista.",
    ),
    build=(
        ("Django: carga anticipada",
         "orders = Order.objects.filter(shop=shop).select_related('customer')   # JOIN\n"
         "orders = Order.objects.filter(shop=shop).prefetch_related('items')    # lote IN"),
        ("SQL: los dos arreglos",
         "SELECT * FROM customers WHERE id IN (17, 42, 99);\n"
         "SELECT o.*, c.name FROM orders o JOIN customers c ON c.id = o.customer_id\n"
         " WHERE o.shop_id = 7;"),
        ("Encuéntralo en producción: cuenta consultas por petición",
         "# registra len(connection.queries) por petición (Django), o usa un detector de N+1\n"
         "# del ORM (Bullet en Rails, nplusone en Python) en los tests"),
    ),
    checklist=(
        "Cuenta las consultas por petición en los tests; falla el test si una lista hace una consulta por elemento.",
        "Carga los datos relacionados por adelantado (JOIN o IN) siempre que pintes una lista.",
        "Mira los viajes, no solo el tiempo de cada consulta: una consulta rápida enviada 100 veces es una página lenta.",
        "Pagina las listas largas: N crece con los datos.",
        "En GraphQL o resolvers anidados, agrupa por petición con un DataLoader.",
    ),
    refs=(
        Ref("Django: select_related and prefetch_related",
            "https://docs.djangoproject.com/en/5.1/ref/models/querysets/#select-related",
            "Carga anticipada con un JOIN o con una segunda consulta agrupada (en inglés)."),
        Ref("Rails guides: Eager loading associations",
            "https://guides.rubyonrails.org/active_record_querying.html#eager-loading-associations",
            "includes, preload y eager_load, y el problema N+1 que resuelven (en inglés)."),
        Ref("SQLAlchemy: Relationship loading techniques",
            "https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html",
            "Carga lazy, joined y selectin (en inglés)."),
        Ref("GraphQL DataLoader",
            "https://github.com/graphql/dataloader",
            "Agrupar y cachear por petición en resolvers anidados (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/n_plus_one_queries/es/main.py y mira cómo las consultas por página bajan a 2.",
        "Luego espera una BD lenta: ¿por qué las páginas siguen pasando de 40 ms?",
        "Haz la etapa 2 y compara el p99 en la siguiente ralentización.",
        "Prueba asyncio.gather con las N consultas: ¿le gusta más a la base de datos?",
    ),
)

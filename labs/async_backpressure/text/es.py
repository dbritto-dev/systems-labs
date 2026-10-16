"""Laboratorio async_backpressure, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Contrapresión en asyncio"
SUMMARY = "Una tubería asyncio de un flujo de eventos a una base de datos. Memoria acotada aunque una etapa vaya lenta."
PARAMS = {"rate": "eventos por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"slow": "LENTO", "spike": "PICO", "burst": "RÁFAGA", "outage": "CAÍDA", "calm": "CALMA"}
CAUSES = {
    "vacuum": "autovacuum en la tabla de eventos: cada inserción espera al disco",
    "compaction": "la base de datos compacta su almacenamiento: las escrituras se arrastran",
    "throttled": "la base de datos nos limita: pasamos de las escrituras contratadas",
    "backup": "la copia de seguridad nocturna satura los discos de la base de datos",
    "gc_pause": "el servicio de enriquecimiento está atascado en pausas largas del recolector de basura",
    "cold_cache": "el servicio de enriquecimiento se volvió a desplegar: su caché está fría",
    "db_failover": "la base de datos del servicio de enriquecimiento cambia a su réplica",
    "noisy_neighbour": "un vecino ruidoso en las máquinas del servicio de enriquecimiento",
    "backfill": "el origen vuelve a enviar los eventos de ayer",
    "viral": "una publicación se vuelve viral: llueven los clics",
    "replay": "el origen reenvía lo que guardó durante su propia caída",
    "campaign": "una campaña publicitaria llega a todos los usuarios a la vez",
    "failover": "la base de datos cambia a su réplica",
    "proxy_restart": "el intermediario de la base de datos se reinicia tras un cambio de configuración",
    "network": "una partición de red entre nosotros y la base de datos",
    "cert_expired": "el certificado TLS de la base de datos caducó hasta que lo renovaron",
}

STAGES = [
    StageText("Colas sin límite",
              "Reto: con el destino lento las colas crecen hasta que matan el proceso y todo se pierde.",
              "Etapa 1: colas acotadas: Queue(maxsize=QUEUE_SIZE)"),
    StageText("Colas acotadas",
              "Reto: sin muertes, pero la fuente parada desborda el origen y los lotes fijos no rinden.",
              "Etapa 2: créditos, lotes adaptativos, descartar baja"),
    StageText("Créditos + lotes adaptativos",
              "Resuelto: memoria acotada, baja descartada y contada, alta toda escrita, lotes que crecen.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "Pipeline.run() debe escribir"),
    "oom": GoalText("Muertes OOM = 0", "acota las colas"),
    "lost": GoalText("Perdidos = 0", "descarta baja y cuéntalo"),
    "peak": GoalText("Pico mem. ≤ 80%", "créditos en cada etapa"),
    "throughput": GoalText("Caudal ≥ 80%", "agrupa lo que hay en cola"),
    "p99": GoalText("p99 después < 1s", "ventanas acotadas"),
}

LEGEND = {"idle": "en reposo", "event": "evento", "waiting": "esperó 0.25,1,4s", "written": "escrito",
          "shed": "descartado (baja)", "lost": "perdido", "limit": "80% memoria", "incident": "incidente"}

STRINGS = {
    # incidentes
    "title_slow": "Destino lento",
    "title_spike": "Pico",
    "title_burst": "Ráfaga",
    "title_outage": "Destino caído",
    "slow_start": "el destino va {n:.0f} veces más lento: {cause}",
    "slow_end": "el destino vuelve a su velocidad",
    "spike_start": "las llamadas de enriquecimiento tardan {n:.0f} veces más: {cause}",
    "spike_end": "el servicio de enriquecimiento vuelve a ir rápido",
    "burst_start": "el origen envía {n:.1f} veces los eventos: {cause}",
    "burst_end": "el origen vuelve a su ritmo de siempre",
    "outage_start": "el destino está caído, toda escritura falla: {cause}",
    "outage_end": "el destino ha vuelto",
    "warn_oom": "{n} muerte(s) por OOM: {lost:,} eventos perdidos con el proceso",
    "warn_upstream": "{n:,} eventos tirados por el origen: su búfer estaba lleno",
    "warn_shed": "{n:,} eventos de baja prioridad descartados (contados)",
    # valores de los objetivos
    "count": "{n:,}",
    # el panel
    "tile_memory": "Memoria",
    "tile_lost": "Perdidos",
    "bar_arrived": "Llegan",
    "bar_written": "Escritos",
    "bar_dropped": "Descartes",
    "limit": "admite {n}/s",
    "title": "Eventos",
    "subtitle": "por segundo, últimos 3 s",
    "head_restarting": "Sin memoria: {n:,} perdidos",
    "head_upstream": "Origen lleno: {n:,} perdidos",
    "head_memory": "Memoria {pct}: las colas crecen",
    "head_shed": "Descarta {n:,.0f} de baja/s, contados",
    "head_paused": "En pausa: {n:,} en el origen",
    "head_slow": "Destino lento: lotes más grandes",
    "head_spike": "Enriquecer va lento: las etapas esperan",
    "head_burst": "El origen envía más de lo normal",
    "head_outage": "Destino caído: se reintenta",
    "head_ok": "Escrituras de ~{n:,} eventos",
    "stat_written": "escritos",
    "stat_lost": "perdidos",
    "stat_shed": "descartados",
    "note_chart": "Gráfica: memoria, % de 256 MiB: base, crudos, analizados, enriquecidos.",
    # los dibujos
    "state_restarting": "SIN MEMORIA",
    "state_memory": "MEMORIA ALTA",
    "state_lost": "SE PIERDEN",
    "state_shed": "DESCARTANDO",
    "state_paused": "EN PAUSA",
    "state_slow": "DESTINO LENTO",
    "state_spike": "ENRIQUECER LENTO",
    "state_burst": "RÁFAGA",
    "state_outage": "DESTINO CAÍDO",
    "pic_mem": "{state} · {pct}",
    "lbl_in": "origen {n}",
    "lbl_a": "A {n}",
    "lbl_b": "B {n}",
    "lbl_c": "C {n}",
    "lbl_down": "CAÍDO",
    "lbl_slow": "{n:.0f}x lento",
    "lbl_rate": "{n}/s",
    "lbl_sink": "destino {state}",
    "lbl_sink_tiny": "dest.",
    "pic_state": "memoria {pct} · {state}",
    # errores en tu código
    "returned": "Pipeline.run() terminó: debe correr para siempre (espera a las etapas en un TaskGroup)",
}

LESSON = Lesson(
    title="Contrapresión en una tubería asyncio",
    one_liner="Un productor rápido y un consumidor lento necesitan un límite entre ellos, o el límite será la memoria.",
    learn=(
        "Una asyncio.Queue() no tiene límite. Cuando la etapa de después va más lenta que la de antes, "
        "la cola crece: una base de datos lenta, un servicio lento o una ráfaga se convierten en "
        "memoria, y la memoria tiene un límite duro. Al pasarlo, el sistema mata el proceso por falta de "
        "memoria (OOM) y todo lo que tenía desaparece, sin que nadie sepa qué eventos.",
        "La contrapresión es la etapa lenta empujando hacia atrás: dale a cada cola un maxsize y `put` "
        "espera mientras está llena. La espera viaja hacia atrás, etapa por etapa, hasta la fuente, que "
        "deja de leer. La memoria queda acotada, pero ahora el atraso lo guarda el origen. Un log "
        "durable (Kafka) puede esperar; un flujo que empuja tiene un búfer pequeño y tira lo que no cabe. "
        "Decide qué pasa en la fuente.",
        "Los créditos hacen explícita la ventana: cada etapa le concede a la anterior cuántos eventos "
        "puede enviarle, y se los devuelve solo cuando esos eventos han seguido su camino. Eso acota los "
        "eventos en la cola y en manos de la etapa siguiente (el lote que se escribe, las llamadas en "
        "curso), y la fuente puede ver que le faltan en vez de quedarse bloqueada.",
        "Agrupa lo que hay en cola. Una escritura cuesta un fijo más un poco por evento; un lote fijo de "
        "50 malgasta un destino lento en ese fijo. Toma un elemento y luego todo lo que ya espera, hasta "
        "el máximo: los lotes son pequeños cuando el destino va rápido y crecen cuando va lento.",
        "Cuando ni los lotes llenos alcanzan, algo tiene que ceder: elígelo tú. Descarta la clase de baja "
        "prioridad, contada y visible, y guarda una reserva de la ventana para la de alta. Un descarte "
        "que cuentas es una decisión; una pérdida por falta de memoria o por un origen desbordado es un "
        "incidente.",
    ),
    watch_for=(
        "Colas sin límite: con el destino lento la memoria sube (naranja en la gráfica) hasta que matan "
        "el proceso; ~10.000 eventos desaparecen, el proceso arranca de nuevo y vuelve a pasar.",
        "Colas acotadas: la memoria queda plana, pero la puerta se cierra (la fuente deja de leer), los "
        "eventos esperan en el origen (naranja oscuro) y se pierden en rojo cuando su búfer se desborda.",
        "Créditos: los eventos de baja prioridad se descartan en gris en la puerta, todos los de alta se "
        "escriben, en lotes de 1.000.",
    ),
    build=(
        ("Python: una cola acotada frena al productor",
         "queue = asyncio.Queue(maxsize=100)\n"
         "await queue.put(item)    # espera mientras hay 100 en cola\n"
         "queue.put_nowait(item)   # en cambio lanza asyncio.QueueFull"),
        ("Python: créditos (un semáforo de n permisos)",
         "await credits.take(len(chunk))   # la ventana tiene sitio\n"
         "next_queue.put_nowait(chunk)\n"
         "...                              # más adelante, cuando siguió su camino:\n"
         "credits.grant(len(chunk))"),
        ("Python: lotes adaptativos",
         "batch = list(await queue.get())\n"
         "while len(batch) < MAX_BATCH and not queue.empty():\n"
         "    batch += queue.get_nowait()\n"
         "await sink.write(batch)"),
        ("Consumidor de Kafka: pausar en vez de acumular",
         "consumer.pause(partitions)    # deja de pedir, sigue en el grupo\n"
         "consumer.resume(partitions)   # cuando la ventana vuelve a tener sitio"),
    ),
    checklist=(
        "Cada cola entre dos etapas tiene un límite, en elementos o mejor en bytes.",
        "El límite cuenta también lo que una etapa tiene en curso, no solo lo que espera en la cola.",
        "El pico de memoria con todas las colas llenas queda bajo el límite del contenedor, con margen.",
        "La fuente tiene una política cuando está llena: pausar (si el origen puede guardarlo) o descartar.",
        "Se descarta por prioridad y se cuenta; nada se pierde sin una métrica.",
        "Los lotes crecen con el atraso, hasta el máximo del destino.",
        "La profundidad de cada cola es una métrica, así ves qué etapa va lenta.",
    ),
    refs=(
        Ref("Armin Ronacher: I'm not feeling the async pressure",
            "https://lucumr.pocoo.org/2020/1/1/async-pressure/",
            "Por qué el código asyncio sin contrapresión se cae, y dónde se esconden los búferes."),
        Ref("Python: colas de asyncio",
            "https://docs.python.org/3/library/asyncio-queue.html",
            "maxsize, put() que espera con la cola llena, put_nowait() y QueueFull."),
        Ref("Reactive Streams",
            "https://www.reactive-streams.org/",
            "Control de flujo por demanda: el suscriptor pide n elementos con request(n)."),
        Ref("Martin Thompson: Smart batching",
            "https://mechanical-sympathy.blogspot.com/2011/10/smart-batching.html",
            "Agrupa lo que esté esperando: lotes pequeños en calma, grandes bajo carga."),
        Ref("Fred Hébert: Queues don't fix overload",
            "https://ferd.ca/queues-don-t-fix-overload.html",
            "Una cola solo retrasa la sobrecarga; acótala y empuja hacia atrás o descarta."),
        Ref("Libro de SRE de Google: Handling overload",
            "https://sre.google/sre-book/handling-overload/",
            "Criticidad: descarta primero el trabajo menos importante, y cuéntalo."),
        Ref("Node.js: Backpressuring in streams",
            "https://nodejs.org/en/learn/modules/backpressuring-in-streams",
            "La misma idea en otro entorno: highWaterMark y write() que devuelve false."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/async_backpressure/es/main.py y mira cómo desaparecen las muertes; "
        "luego mira la puerta.",
        "Después mira el final del primer incidente: ¿cuántos eventos tiró el origen?",
        "Haz la etapa 2 y prueba --seed 5: una caída del destino a la 1:57 y luego picos de enriquecimiento.",
    ),
)

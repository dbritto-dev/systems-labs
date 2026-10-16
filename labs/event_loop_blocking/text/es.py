"""Laboratorio event_loop_blocking, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Bucle de eventos bloqueado"
SUMMARY = "Un solo bucle asyncio, y llamadas bloqueantes dentro. Pásalas a hilos, luego a pools acotados."
PARAMS = {"rate": "peticiones por segundo en un día normal"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"upload": "FOTOS", "slow": "LENTO", "report": "CARGA", "gc": "PAUSA", "done": "FIN", "fast": "NORMAL",
         "calm": "CALMA"}
CAUSES = {
    "wedding_photos": "una fotógrafa sube una boda entera, a resolución completa",
    "catalogue_import": "un comercio importa un catálogo de 40,000 fotos de productos",
    "camera_roll_sync": "una nueva versión de la aplicación sincroniza el carrete de cada usuario",
    "photo_migration": "una migración vuelve a procesar fotos antiguas por la ruta de subida",
    "db_lock": "una migración de esquema retiene un bloqueo: las consultas de pedidos esperan",
    "partner_api": "la API del socio de pagos se degrada",
    "dns_resolver": "el resolvedor DNS va lento: cada conexión nueva lo espera",
    "db_failover": "la base de datos cambia de primaria: las consultas esperan a la nueva",
    "month_end": "cierre de mes: finanzas exporta todos los informes a la vez",
    "dashboard_refresh": "un panel refresca su exportación en cada pestaña abierta",
    "partner_export": "el proceso nocturno de un socio descarga exportaciones completas",
    "scraper": "un rastreador encuentra la ruta de exportación",
    "cache_refill": "rellenar una caché crea millones de objetos pequeños",
    "big_import": "una importación masiva construye grafos de objetos enormes",
    "memory_leak": "una fuga en una biblioteca hace crecer la memoria sin parar",
    "cgroup_throttle": "el contenedor llega a su cuota de CPU y lo frenan",
}

STAGES = [
    StageText("Llamadas síncronas en el bucle",
              "Reto: una llamada bloqueante para el bucle entero: todo espera y los chequeos fallan.",
              "Etapa 1: await to_thread(call) en vez de call()"),
    StageText("Delegado a hilos",
              "Reto: el bucle queda libre, pero un solo GIL y una cola sin límite: trabajo para nadie.",
              "Etapa 2: un pool acotado por tipo de trabajo; vigila el retardo"),
    StageText("Ejecutores acotados",
              "Resuelto: CPU en procesos, E/S en hilos, cola llena = 503, y el retardo vigilado.",
              "Todas las etapas hechas"),
]

GOALS = {
    "lag": GoalText("Retardo p99<50ms", "delega lo bloqueante"),
    "health": GoalText("Fallos salud = 0", "no bloquees el bucle"),
    "light": GoalText("Ligeras p99<100ms", "deja libre el bucle"),
    "served": GoalText("Pesadas ok ≥ 70%", "la CPU, en procesos"),
    "queued": GoalText("En cola ≤ 50", "cola acotada: 503 si llena"),
    "watched": GoalText("Vigilado ≥ 90%", "arranca un vigilante"),
}

LEGEND = {"idle": "en reposo", "waits": "espera", "served": "servida", "shed": "503 al instante", "failed": "fallida",
          "own": "trabajo del bucle", "io": "E/S bloqueante", "cpu": "trabajo de CPU", "gil": "espera al GIL",
          "gc": "pausa de basura", "budget": "retardo máximo", "incident": "incidente"}

STRINGS = {
    "note_dots": "Los puntos son una muestra, más lentos (decorativo).",
    "note_chart": "Gráfica: el peor retardo del bucle en cada segundo, del color de lo que lo retuvo.",
    # los dibujos
    "blocked": "BLOQUEO {ms:.0f}ms",
    "lane_state": "{state} {lag}",
    "lane_busy": "{state} +{n}",
    "cluster_state": "{state} · {pools}",
    "cluster_down": "{state}: reiniciando",
    "pool_threads": "hilos {busy}/{n} +{q}",
    "pool_default": "por defecto {busy}/{n} +{q}",
    "pool_procs": "procesos {busy}/{n} +{q}",
    "no_pools": "sin pools",
    "call_db": "una consulta síncrona",
    "call_http": "una llamada HTTP síncrona",
    "call_resize": "un redimensionado",
    "call_report": "un json.dumps",
    "call_gc": "una pausa de basura",
    "call_own": "código del manejador",
    "call_pickle": "serializar",
    # incidentes
    "uploads": "Lote de fotos",
    "slow_dep": "Dependencia lenta",
    "reports": "Ráfaga de informes",
    "gc": "Pausas de basura",
    "uploads_start": "{cores:.1f} núcleos de redimensionar imágenes: {cause}",
    "uploads_end": "el lote de fotos termina",
    "slow_dep_start": "llamadas síncronas a la BD y HTTP {times:.0f} veces más lentas: {cause}",
    "slow_dep_end": "la dependencia vuelve a ir rápida",
    "reports_start": "{cores:.1f} núcleos de json.dumps: {cause}",
    "reports_end": "la ráfaga de informes termina",
    "gc_start": "el proceso se para ~{ms:.0f} ms, una y otra vez: {cause}",
    "gc_end": "las pausas de basura terminan",
    "warn_killed": "matado: 3 chequeos de salud seguidos sin respuesta",
    "warn_stall": "{what} retuvo el bucle {ms:.0f} ms: nada más corrió",
    "warn_queued": "{n} llamadas en cola en los ejecutores, y creciendo",
    "warn_shed": "{n:.0f} peticiones respondidas con 503 al instante: una cola está llena",
    "warn_watchdog": "tu vigilante informa {ms:.0f} ms de retardo del bucle",
    # el panel
    "tile_lag": "Bucle",
    "tile_light": "p99",
    "tile_queued": "En cola",
    "toplist": "Peticiones",
    "bar_asked": "Pedidas",
    "bar_served": "Servidas",
    "bar_refused": "Rechazos",
    "limit_lag": "retardo máximo",
    "head_down": "Matado por el orquestador: reiniciando, toda petición falla",
    "head_blocked": "{what} retiene el bucle: {ms:.0f} ms, nada más corre",
    "head_lag": "Retardo p99 del bucle {ms:.0f} ms: toda petición lo espera",
    "head_gc": "Pausas de basura paran el bucle {ms:.0f} ms: no es tu código",
    "head_queued": "{n:,} llamadas en cola: más de lo que el pool hace a tiempo",
    "head_shed": "{n} respondidas con 503 al instante: el pool está lleno",
    "head_gil": "CPU en hilos: el bucle se turna con ellos por el GIL",
    "head_ok": "Retardo del bucle {ms:.0f} ms: el bucle sigue libre",
}

LESSON = Lesson(
    title="Bucle de eventos bloqueado",
    one_liner="Un solo bucle asyncio atiende todas las peticiones: una llamada bloqueante dentro las para "
              "todas. Pasa la E/S bloqueante a hilos y la CPU a procesos, acota cada cola y vigila el retardo.",
    learn=(
        "asyncio ejecuta cada manejador en un solo hilo, el bucle de eventos. Un manejador solo deja correr a "
        "los demás cuando hace await. Una llamada bloqueante (un driver síncrono como psycopg2, requests, un "
        "redimensionado con Pillow, un json.dumps enorme) nunca hace await: mientras corre no avanza ninguna "
        "otra petición, no salta ningún temporizador y el chequeo de salud también espera. Tres chequeos "
        "fallidos y el orquestador mata un proceso que solo estaba ocupado.",
        "El síntoma es el retardo del bucle: cuánto tarda en correr una tarea respecto a cuándo le tocaba. "
        "Mídelo con un vigilante (duerme 100 ms y mira cuánto tarde te despiertan) y publícalo como métrica; "
        "el modo de depuración de asyncio además registra cada tarea más lenta que "
        "loop.slow_callback_duration.",
        "asyncio.to_thread / loop.run_in_executor llevan una llamada bloqueante a un pool de hilos: el bucle "
        "queda libre. Es lo correcto para E/S bloqueante, que suelta el GIL mientras espera. El código Python "
        "que usa CPU retiene el GIL: ocho hilos siguen calculando de uno en uno, y el hilo del bucle se turna "
        "con ellos (el intérprete cambia cada 5 ms, sys.getswitchinterval()). Las versiones sin GIL (PEP 703) "
        "lo cambian, pero casi todos los despliegues aún tienen GIL.",
        "Dale a cada tipo de trabajo su propio ejecutor: un ProcessPoolExecutor con un proceso por núcleo para "
        "la CPU (cada proceso tiene su GIL; los argumentos viajan serializados con pickle) y un pool de hilos "
        "para la E/S bloqueante. Pools separados son bulkheads: una base de datos lenta llena "
        "el de E/S, no el que redimensiona imágenes.",
        "Las colas de los ejecutores no tienen límite. En una ráfaga crecen mientras dure, cada llamada en "
        "ellas espera más que su usuario, y el trabajo se hace igual para nadie. Acota cada cola y rechaza "
        "pronto (503 con Retry-After): un no rápido es mejor que un timeout lento.",
    ),
    watch_for=(
        "Llamadas síncronas en el bucle: el nodo del bucle se pone rojo, el indicador se llena, BLOQUEO cuenta hacia arriba y la puerta se cierra: matan la instancia.",
        "Delegado a hilos: el bucle sigue verde, pero ocho hilos se turnan por un solo GIL y la cola bajo el dibujo sube a cientos.",
        "Ejecutores acotados: cuatro procesos calculan a la vez, los hilos de E/S esperan en paralelo y una cola llena responde 503 en amarillo.",
    ),
    build=(
        ("Python: E/S bloqueante y CPU a pools acotados",
         "io = ThreadPoolExecutor(max_workers=16)  # E/S bloqueante: hilos que esperan\n"
         "cpu = ProcessPoolExecutor(max_workers=os.cpu_count())  # CPU: un proceso por núcleo\n"
         "MOST = {io: 16 + 32, cpu: 4 + 8}  # en marcha + en cola, como mucho\n"
         "in_flight = {io: 0, cpu: 0}\n"
         "\n"
         "async def run_blocking(fn, *args, cpu_bound=False):\n"
         "    pool = cpu if cpu_bound else io\n"
         "    if in_flight[pool] >= MOST[pool]:\n"
         "        raise HTTPException(503, headers={\"Retry-After\": \"2\"})\n"
         "    in_flight[pool] += 1\n"
         "    try:\n"
         "        loop = asyncio.get_running_loop()\n"
         "        return await loop.run_in_executor(pool, fn, *args)\n"
         "    finally:\n"
         "        in_flight[pool] -= 1"),
        ("Python: un vigilante del retardo del bucle",
         "async def watchdog(every=0.1):\n"
         "    loop = asyncio.get_running_loop()\n"
         "    while True:\n"
         "        t = loop.time()\n"
         "        await asyncio.sleep(every)\n"
         "        LOOP_LAG.observe(loop.time() - t - every)  # un histograma de Prometheus\n"
         "\n"
         "loop.slow_callback_duration = 0.05  # con PYTHONASYNCIODEBUG=1: registra tareas lentas"),
        ("Kubernetes: un chequeo de vida que tolera una parada corta",
         "livenessProbe:\n"
         "  httpGet: {path: /health, port: 8080}\n"
         "  periodSeconds: 10\n"
         "  timeoutSeconds: 1\n"
         "  failureThreshold: 3"),
    ),
    checklist=(
        "Ninguna llamada bloqueante en un manejador async: drivers síncronos, requests, time.sleep, json.dumps enormes, imágenes.",
        "E/S bloqueante a un pool de hilos dimensionado para esperar; CPU a un pool de procesos del tamaño de los núcleos.",
        "Un ejecutor por tipo de trabajo (bulkheads), cada uno con una cola acotada que responde 503 si está llena.",
        "Usa drivers async donde existan (asyncpg, httpx.AsyncClient): no hace falta ejecutor.",
        "Mide el retardo del bucle todo el tiempo y alerta con él; activa la depuración de asyncio en preproducción.",
        "Que los chequeos de salud sean baratos, y su timeout y umbral, mayores que la peor parada que aceptas.",
        "Métricas: retardo p99 del bucle, longitud y espera de las colas, 503, CPU por proceso, tiempo de pausa de basura.",
    ),
    refs=(
        Ref("Python: Desarrollar con asyncio, ejecutar código bloqueante",
            "https://docs.python.org/3/library/asyncio-dev.html#running-blocking-code",
            "Por qué el código bloqueante no debe correr en el bucle, y el registro de tareas lentas."),
        Ref("Python: loop.run_in_executor",
            "https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.run_in_executor",
            "Pools de hilos y de procesos desde asyncio, y asyncio.to_thread."),
        Ref("Python: concurrent.futures",
            "https://docs.python.org/3/library/concurrent.futures.html",
            "ThreadPoolExecutor y ProcessPoolExecutor, y sus valores por defecto."),
        Ref("David Beazley: charlas sobre el GIL de Python",
            "https://www.dabeaz.com/GIL/",
            "Por qué los hilos que usan CPU se turnan, y cómo frenan a los de E/S."),
        Ref("Node.js: Don't Block the Event Loop",
            "https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop",
            "El mismo problema en otro entorno: partir y delegar el trabajo."),
        Ref("Kubernetes: chequeos de vida, de preparación y de arranque",
            "https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/",
            "Cómo el timeout y el umbral de fallos de un chequeo deciden cuándo matan un contenedor ocupado."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/event_loop_blocking/es/main.py y mira el bucle seguir verde mientras crece la cola.",
        "Haz la etapa 2 y mira cuatro procesos calcular a la vez, y los 503 cuando la cola está llena.",
        "Pon CPU_PROCESSES a 16 (más procesos que núcleos) o CPU_QUEUE a 1000, y mira qué cambia.",
    ),
)

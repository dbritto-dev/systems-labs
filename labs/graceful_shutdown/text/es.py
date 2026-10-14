"""Laboratorio graceful_shutdown, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Apagado ordenado"
SUMMARY = "Los despliegues mandan SIGTERM a 6 instancias tras un balanceador. Drena, y antes sal del balanceador."
PARAMS = {"rate": "peticiones de usuarios por segundo"}

INCIDENT = IncidentText("Apagado", "el apagado", "el próximo apagado")
VERBS = {"deploy": "RELEVO", "drain": "DRENA", "scale_in": "REDUCE", "done": "LISTO"}
CAUSES = {
    "release": "sale una nueva versión",
    "config_change": "un cambio de configuración reinicia todas las instancias",
    "base_image": "sale una imagen base parcheada (el arreglo de una vulnerabilidad)",
    "rollback": "una vuelta atrás a la versión anterior",
    "kernel_patch": "drenan su nodo para parchear el núcleo del sistema",
    "node_upgrade": "drenan su nodo para actualizar el grupo de nodos",
    "spot_reclaim": "reclaman su nodo spot (con 2 minutos de aviso) y lo drenan",
    "traffic_dip": "el tráfico baja y el autoescalado quita una instancia",
    "night_schedule": "una reducción programada para la noche",
}

STAGES = [
    StageText("Salir de golpe",
              "Reto: SIGTERM corta lo que está en curso, y el balanceador aún manda peticiones allí.",
              "Etapa 1: drena: deja de aceptar, termina lo que está en curso y sal"),
    StageText("Drenar",
              "Reto: nada se corta, pero el balanceador aún manda hasta que fallan sus comprobaciones.",
              "Etapa 2: deja de estar lista, espera al balanceador y luego drena"),
    StageText("Primero, no lista",
              "Resuelto: el balanceador deja de mandar primero y luego se drena lo que está en curso.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "on_sigterm() no debe fallar"),
    "errors": GoalText("Errores ≤ 0.1%", "primero deja de estar lista"),
    "cut": GoalText("Cortadas en curso = 0", "drena antes de salir"),
    "capacity": GoalText("Sirven ≥ 5 de 6", "sirve hasta que te saquen"),
    "exited": GoalText("Sale antes de SIGKILL", "drena con un plazo"),
}

LEGEND = {"idle": "en reposo", "request": "petición", "waits": "espera", "served": "servida",
          "failed": "fallida", "serving": "sirve", "starting": "arranca", "draining": "drena",
          "terminated": "terminada", "limit": "una instancia", "incident": "apagado"}

STRINGS = {
    "note_dots": "Los puntos son una muestra, más lentos (estético).",
    # los dibujos
    "topology": "3 nodos del balanceador → 6 instancias",
    "state_ok": "SIRVEN {n}/{of}",
    "state_starting": "ARRANCA s{slot} · {n}/{of}",
    "state_leaving": "SALIENDO s{slot} · {n}/{of}",
    "state_draining": "DRENANDO s{slot} · {n}/{of}",
    "state_refusing": "RECHAZA s{slot} · {n}/{of}",
    "state_cut": "CORTE s{slot} · {n}/{of}",
    # incidentes
    "deploy": "Despliegue",
    "drain": "Drenado de nodo",
    "scale_in": "Reducción",
    "deploy_start": "Despliegue gradual de {n} instancias, una a una: {cause}",
    "deploy_end": "la última instancia vieja ya tiene su SIGTERM; el balanceador se ha puesto al día",
    "drain_start": "s{slot} recibe SIGTERM; arranca otra en otro nodo: {cause}",
    "drain_end": "s{slot}: el balanceador se ha puesto al día",
    "scale_start": "s{slot} recibe SIGTERM, sin reemplazo: {cause}",
    "scale_end": "el autoescalado vuelve a añadir s{slot} en 5 s",
    "warn_failed": "{n:.0f} peticiones fallidas en un segundo: enviadas a s{slot}",
    "warn_killed": "s{slot} matada con SIGKILL a los 30 s: {cut} cortadas",
    "warn_cut": "s{slot} salió con {cut} en curso: cortadas",
    # el panel
    "tile_errors": "Fallos",
    "tile_cut": "Cortadas",
    "tile_serving": "Sirven",
    "toplist": "Peticiones",
    "bar_new": "A otras",
    "bar_old": "A viejas",
    "bar_failed": "Fallidas",
    "limit_one": "una: {n}/s",
    "head_failed": "{n} rechazadas en s{slot}: aún en rotación",
    "head_failed_any": "{n} peticiones fallidas",
    "head_cut": "s{slot} salió: {n} cortadas en curso",
    "head_draining": "s{slot} drena: {n} aún en curso",
    "head_waiting": "s{slot} aún en rotación: {n} en curso",
    "head_starting": "s{slot} arranca; aún fuera de rotación",
    "head_steady": "Las {n} instancias sirven",
    "note_chart": "Gráfica: peticiones/s a instancias viejas, y fallos.",
    # errores en tu código
    "bad_timeout": "drained() necesita un número de segundos (o None), no {value}",
}

LESSON = Lesson(
    title="Apagado ordenado",
    one_liner="Un despliegue es un apagado. Sal primero del balanceador de carga, luego drena lo que está en curso, y sal antes de que te maten.",
    learn=(
        "Cada despliegue, reducción de escala, drenado de nodo o instancia spot reclamada termina una "
        "instancia igual: el orquestador le manda SIGTERM y, tras un periodo de gracia (30 s en "
        "Kubernetes), SIGKILL. Lo que pasa entre medias depende de la aplicación, y lo normal es salir de golpe.",
        "Salir de golpe corta cada petición en curso (el usuario recibe un 502 o una conexión reiniciada), "
        "cada WebSocket y cada flujo, y cada conexión persistente. Y el balanceador de carga aún no lo sabe: "
        "se entera solo cuando sus comprobaciones de salud fallan varias veces seguidas, así que durante "
        "segundos sigue mandando conexiones nuevas a una instancia que ya no está.",
        "Drenar arregla la primera mitad: dejar de aceptar conexiones nuevas, cerrar las conexiones "
        "persistentes ociosas (y responder a las demás con 'Connection: close', y pedir a los flujos que se "
        "reconecten), esperar a que termine lo que está en curso, y salir. No se corta nada. Pero un socket "
        "que ya no escucha rechaza las conexiones que el balanceador aún manda, así que los usuarios siguen "
        "viendo errores hasta que el balanceador se da cuenta.",
        "El orden es el arreglo: primero haz fallar la comprobación de disponibilidad (readiness) y sigue "
        "sirviendo, espera a que cada nodo del balanceador haya sacado a la instancia de la rotación "
        "(comprobaciones × intervalo, más lo que tarda en aplicarlo), y luego drena. En Kubernetes esa espera "
        "se suele poner en un gancho preStop ('sleep 10'). Ponle un plazo al drenado para que el proceso "
        "salga antes de que acabe el periodo de gracia: SIGKILL lo corta todo.",
        "La espera también protege la capacidad. El orquestador pasa a la siguiente instancia en cuanto la "
        "nueva está lista, a menudo antes de que el balanceador le mande tráfico. Una instancia vieja que "
        "sigue sirviendo mientras espera cubre ese hueco; una que sale de golpe deja dos instancias fuera.",
    ),
    watch_for=(
        "Salir de golpe: la instancia se pone roja (el balanceador aún le manda) y gris; las peticiones mueren en rojo.",
        "Drenar: no se corta nada, pero la instancia rechaza conexiones nuevas durante segundos: rojo en la puerta.",
        "Primero, no lista: la instancia sigue naranja mientras sirve y drena, y pasa a gris sin ruido.",
    ),
    build=(
        ("Kubernetes: espera al balanceador en preStop, y un periodo de gracia que cubra el drenado",
         "spec:\n"
         "  terminationGracePeriodSeconds: 30\n"
         "  containers:\n"
         "  - name: app\n"
         "    lifecycle:\n"
         "      preStop:\n"
         "        exec: {command: [\"sleep\", \"10\"]}\n"
         "    readinessProbe:\n"
         "      httpGet: {path: /ready, port: 8080}\n"
         "      periodSeconds: 2\n"
         "      failureThreshold: 3"),
        ("Go: deja de estar lista, espera, y luego Shutdown con un plazo",
         "<-sigterm\n"
         "ready.Store(false)                    // /ready responde 503\n"
         "time.Sleep(10 * time.Second)          // el balanceador la saca\n"
         "ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)\n"
         "defer cancel()\n"
         "srv.Shutdown(ctx) // deja de escuchar, cierra las ociosas, espera al resto"),
        ("Node.js: deja de estar lista (/ready responde 503), espera, cierra, un plazo",
         "process.on('SIGTERM', async () => {\n"
         "  ready = false;\n"
         "  await sleep(10_000);\n"
         "  server.close(() => process.exit(0));\n"
         "  server.closeIdleConnections();\n"
         "  setTimeout(() => process.exit(1), 15_000).unref();\n"
         "});"),
    ),
    checklist=(
        "Atiende SIGTERM: nunca salgas de golpe con peticiones en curso. Asegúrate de que la señal llega a tu proceso (PID 1, forma exec).",
        "Primero deja de estar lista, y sigue sirviendo hasta que el balanceador te saque: espera comprobaciones × intervalo más su retardo.",
        "Luego deja de aceptar, cierra las conexiones persistentes ociosas, manda 'Connection: close', pide a WebSockets y flujos que se reconecten.",
        "Drena con un plazo, y sal antes de que acabe el periodo de gracia: SIGKILL lo corta todo.",
        "Métricas: 5xx y conexiones reiniciadas por despliegue, peticiones en curso al salir, tiempo de apagado, instancias que sirven durante un despliegue.",
    ),
    refs=(
        Ref("Kubernetes: Pod lifecycle, termination of Pods",
            "https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination",
            "SIGTERM, preStop, el periodo de gracia y SIGKILL, y los endpoints que se quitan en paralelo (en inglés)."),
        Ref("Kubernetes: Container lifecycle hooks",
            "https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/",
            "El gancho preStop corre antes de SIGTERM, dentro del periodo de gracia (en inglés)."),
        Ref("AWS: Health checks for Application Load Balancer target groups",
            "https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html",
            "Intervalo, umbral de fallos, y cómo sale un destino de la rotación (en inglés)."),
        Ref("Go: http.Server.Shutdown",
            "https://pkg.go.dev/net/http#Server.Shutdown",
            "Cierra los sockets que escuchan, luego las conexiones ociosas, y espera a las activas hasta que acabe el contexto (en inglés)."),
        Ref("AWS Load Balancer Controller: Pod readiness gate",
            "https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/deploy/pod_readiness_gate/",
            "Por qué un despliegue puede adelantarse al balanceador, y cómo hacerlo esperar (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/graceful_shutdown/es/main.py y mira cómo paran los cortes mientras siguen los errores.",
        "Haz la etapa 2 y mira cómo la instancia sigue naranja y sirviendo hasta que el balanceador la suelta.",
        "Prueba a esperar exactamente comprobaciones × intervalo, sin el retardo propio del balanceador: ¿cuántos errores vuelven?",
    ),
)

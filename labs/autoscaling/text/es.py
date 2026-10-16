"""Laboratorio autoscaling, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Autoescalado"
SUMMARY = "Una flota que debe seguir al tráfico. Escala por CPU de una en una, luego sigue las peticiones por instancia."
PARAMS = {"rate": "peticiones de usuarios por segundo en un día medio (el día oscila ±40%)"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"surge": "PICO", "eases": "CALMA", "drop": "BAJA", "back": "VUELVE", "noisy": "RUIDO",
         "quiet": "LIMPIA", "cold": "FRÍO", "warm": "LISTO"}
CAUSES = {
    "tv_ad": "sale un anuncio en la tele y los espectadores abren la aplicación",
    "marketing_push": "sale un correo de marketing a todos los usuarios",
    "viral_post": "una publicación sobre nosotros se vuelve viral",
    "flash_sale": "empieza una venta relámpago",
    "region_failover": "el tráfico se traslada a otra región",
    "upstream_outage": "una caída aguas arriba: la pasarela que va delante descarta peticiones",
    "client_bug": "una versión de la aplicación móvil deja de llamarnos",
    "batch_job": "un proceso por lotes corre en las mismas máquinas",
    "backup": "una copia de seguridad comprime archivos en las mismas máquinas",
    "log_shipper": "un enviador de registros se queda atrás y quema CPU",
    "deploy": "un despliegue gradual reinicia las instancias, lote a lote",
    "config_push": "un cambio de configuración reinicia las instancias, lote a lote",
    "node_rotation": "un parche de seguridad rota las máquinas, lote a lote",
}

STAGES = [
    StageText("Flota fija",
              "Reto: una flota fija nunca crece: el pico la satura, y de noche está ociosa.",
              "Etapa 1: +1 instancia con CPU sobre 70%, -1 bajo 30%"),
    StageText("Umbrales de CPU",
              "Reto: una instancia por turno se queda atrás en un pico, y la CPU es una señal engañosa.",
              "Etapa 2: sigue peticiones/s por instancia; reduce despacio"),
    StageText("Seguimiento de objetivo",
              "Resuelto: la flota sigue al tráfico en pasos proporcionales, con margen y sin oscilar.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "desired() debe dar un int"),
    "served": GoalText("Servidas ≥ 99%", "da pasos proporcionales"),
    "p99": GoalText("p99 < 1s", "ajusta la flota al tráfico"),
    "headroom": GoalText("Margen ≥ 50%", "objetivo: 10 pet/s por inst."),
    "flaps": GoalText("Oscilaciones ≤ 2", "reduce despacio: estabiliza"),
    "cost": GoalText("Costo ≤ ideal+50%", "sigue peticiones, no CPU"),
}

LEGEND = {"idle": "en reposo", "request": "petición", "waits": "espera / cola", "served": "servida",
          "failed": "timeout", "warm": "instancia caliente", "warming": "calentando", "booting": "arrancando",
          "short": "faltan", "max": "flota máxima", "incident": "incidente"}

STRINGS = {
    "note_dots": "Los puntos son una muestra, más lentos (decorativo).",
    "note_chart": "Gráfica: la flota en cada segundo, y en rojo las instancias que le faltan para el objetivo.",
    # los dibujos
    "fleet_state": "{state} {n}+{booting}",
    "cluster_state": "{state}  {n} activas · {booting} arrancando · necesita {need}",
    # el dibujo de relevo: la carga de las instancias, la flota que sirve / la necesaria
    "relay_load": "carga {load:.0%}",
    "relay_fleet": "sirven {n}/{need}",
    # incidentes
    "surge": "Pico de tráfico",
    "drop": "Bajada de tráfico",
    "noisy": "CPU ruidosa",
    "cold": "Ola de arranques en frío",
    "surge_start": "el tráfico sube a {times:.1f}x: {cause}",
    "surge_end": "el pico se calma",
    "drop_start": "el tráfico baja al {share:.0%}: {cause}",
    "drop_end": "el tráfico vuelve, poco a poco",
    "noisy_start": "la CPU marca hasta +{cpu:.0%} en cada máquina: {cause}",
    "noisy_end": "el ruido de CPU se ha ido",
    "cold_start": "el {share:.0%} de las instancias a la vez se reinicia en frío: {cause}",
    "cold_end": "todas las instancias vuelven a estar calientes",
    "warn_timeouts": "{n:.0f} peticiones con timeout en un segundo (504)",
    "warn_flap": "oscilación: {n} instancias añadidas y quitadas en 30 s",
    # el panel
    "tile_headroom": "Margen",
    "tile_cost": "Costo",
    "toplist": "Flota",
    "toplist_sub": "instancias ahora",
    "bar_fleet": "Flota",
    "bar_needed": "Necesita",
    "bar_actions": "Acc/10m",
    "limit_max": "máx {n}",
    "head_timeouts": "{n} peticiones con timeout: la flota es pequeña",
    "head_flapping": "Oscila: {n} instancias añadidas y quitadas en 30 s",
    "head_booting": "{n} arrancando: el pico va por delante de la flota",
    "head_short": "Necesita {need}, tiene {n}: hay que crecer",
    "head_waste": "Necesita {need}, paga {n}: hay que reducir",
    "head_noisy": "La CPU marca {cpu:.0%}; el tráfico no ha cambiado",
    "head_fits": "{n} instancias para {need} necesarias: en el objetivo",
    # errores en tu código
    "bad_desired": "desired() devolvió {value}: debe ser un int, el número de instancias que quieres",
}

LESSON = Lesson(
    title="Autoescalado",
    one_liner="Haz crecer y encoger la flota con el tráfico: pasos proporcionales sobre una señal de carga, "
              "margen para el tiempo de arranque, y reducir despacio para no oscilar.",
    learn=(
        "El tráfico nunca es plano: sigue al día, llega a ráfagas y salta cuando sale un anuncio en la tele "
        "o una publicación se vuelve viral. Una flota fija está dimensionada para un momento: se satura en "
        "los picos y de noche se paga ociosa.",
        "Un autoescalador mira las métricas recientes cada pocos segundos y fija el número deseado de "
        "instancias. Una instancia nueva todavía no es capacidad: arranca (20-40 s, pagada, sin servir nada) "
        "y luego sirve despacio mientras se calientan sus cachés y su JIT. Lo que pides ahora llega medio "
        "minuto después.",
        "Las reglas de umbral (una instancia más con la CPU sobre 70%, una menos bajo 30%) son lentas: una "
        "instancia por turno no puede seguir a un tráfico que se duplica en un minuto. Y la CPU engaña: un "
        "proceso por lotes en la misma máquina, un JIT en frío o la recolección de basura la suben sin más "
        "tráfico.",
        "El seguimiento de objetivo (target tracking) calcula de un solo paso la flota que necesita la carga: "
        "peticiones/s divididas entre las peticiones/s que quieres por instancia. Pon el objetivo muy por "
        "debajo del máximo: ese margen absorbe las ráfagas y cubre el arranque mientras llegan las nuevas.",
        "Dos reglas más lo mantienen tranquilo. Cuenta las instancias que aún arrancan o se calientan como "
        "parte de la flota, o cada turno las vuelve a pedir (se pasa de largo). Crece enseguida, pero reduce "
        "solo hasta la recomendación más alta del último minuto más o menos (una ventana de estabilización), "
        "o cada bajón quita instancias que la siguiente ráfaga necesita (oscilación, flapping).",
    ),
    watch_for=(
        "Flota fija: el pico llena las colas y los usuarios acaban en timeout, en rojo; luego, de noche, casi todas las instancias están ociosas.",
        "Umbrales de CPU: un nodo naranja claro por turno, siempre por detrás del pico; con la CPU ruidosa añade instancias para nada.",
        "Seguimiento de objetivo: aparece un lote de instancias a la vez, arranca, se calienta (de naranja a azul), y la flota aguanta antes de encoger.",
    ),
    build=(
        ("AWS: seguimiento de peticiones por destino, con calentamiento",
         "aws autoscaling put-scaling-policy --auto-scaling-group-name web \\\n"
         "  --policy-name requests-per-target --policy-type TargetTrackingScaling \\\n"
         "  --target-tracking-configuration '{\n"
         "    \"PredefinedMetricSpecification\": {\n"
         "      \"PredefinedMetricType\": \"ALBRequestCountPerTarget\",\n"
         "      \"ResourceLabel\": \"app/web/123/targetgroup/web/456\"},\n"
         "    \"TargetValue\": 600}'\n"
         "aws autoscaling update-auto-scaling-group --auto-scaling-group-name web \\\n"
         "  --default-instance-warmup 60"),
        ("Kubernetes: HPA con ventana de estabilización al reducir",
         "apiVersion: autoscaling/v2\n"
         "kind: HorizontalPodAutoscaler\n"
         "spec:\n"
         "  minReplicas: 2\n"
         "  maxReplicas: 40\n"
         "  metrics:\n"
         "  - type: Pods\n"
         "    pods:\n"
         "      metric: {name: http_requests_per_second}\n"
         "      target: {type: AverageValue, averageValue: \"10\"}\n"
         "  behavior:\n"
         "    scaleUp: {stabilizationWindowSeconds: 0}\n"
         "    scaleDown: {stabilizationWindowSeconds: 300}"),
        ("Python: la política de este laboratorio",
         "def desired(self, m):\n"
         "    want = max(MIN_INSTANCES, math.ceil(m.rps / TARGET_RPS))\n"
         "    self.wants.append((m.t, want))  # reduce solo hasta la más alta de los últimos STABILISE s\n"
         "    while self.wants[0][0] <= m.t - STABILISE:\n"
         "        self.wants.popleft()\n"
         "    return max(w for _, w in self.wants)"),
    ),
    checklist=(
        "Escala con una señal de carga que siga al tráfico (peticiones/s o peticiones en curso por instancia), no solo con la CPU.",
        "Dimensiona en un paso proporcional: ceil(carga / objetivo por instancia), no de una instancia en una.",
        "Deja margen: un objetivo cerca del 50-60% de lo que puede una instancia cubre ráfagas y el arranque.",
        "Cuenta en la flota las instancias que arrancan o se calientan, para que el siguiente turno no las pida otra vez.",
        "Crece rápido y reduce despacio (una ventana de estabilización); fija una flota mínima y una máxima.",
        "Métricas: instancias deseadas, en marcha y en servicio; acciones de escalado por hora; p99; costo por petición.",
    ),
    refs=(
        Ref("AWS: Target tracking scaling policies",
            "https://docs.aws.amazon.com/autoscaling/ec2/userguide/as-scaling-target-tracking.html",
            "Eliges una métrica y un valor objetivo; el grupo calcula la capacidad (en inglés)."),
        Ref("AWS: Set the default instance warmup",
            "https://docs.aws.amazon.com/autoscaling/ec2/userguide/ec2-auto-scaling-default-instance-warmup.html",
            "Por qué las instancias que aún se calientan no deben provocar más escalado (en inglés)."),
        Ref("Kubernetes: Horizontal Pod Autoscaling",
            "https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/",
            "La fórmula proporcional, los pods que no están listos y la ventana de estabilización (en inglés)."),
        Ref("Google SRE Workbook: Managing Load",
            "https://sre.google/workbook/managing-load/",
            "Autoescalado, margen, y qué hacer mientras llega la capacidad nueva (en inglés)."),
        Ref("Brendan Gregg: CPU Utilization is Wrong",
            "https://www.brendangregg.com/blog/2017-05-09/cpu-utilization-is-wrong.html",
            "Por qué el porcentaje de CPU mide mal lo cargado que está un servicio (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/autoscaling/es/main.py y mira cómo la flota persigue el pico de una instancia en una.",
        "Haz la etapa 2 y mira cómo arrancan lotes enteros a la vez, y cómo la flota aguanta antes de encoger.",
        "Pon STABILISE a 0 y mira las oscilaciones; pon TARGET_RPS a 18 y mira cómo el pico acaba en timeouts.",
    ),
)

"""Laboratorio rate_limiting, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Limitación de tráfico"
SUMMARY = "Unos pocos clientes inundan la API al azar. Limita a cada uno para que el resto siga funcionando."
PARAMS = {"rate": "peticiones por segundo de todos los clientes juntos, en condiciones normales"}

INCIDENT = IncidentText("Avalancha", "la avalancha", "la próxima avalancha")
VERBS = {"flood": "RÁFAGA", "calm": "CALMA"}
CAUSES = {
    "batch_first": "un proceso por lotes en 5 cuentas envía su trabajo a trozos",
    "batch_chunks": "un proceso por lotes en varias cuentas envía su trabajo a trozos",
    "nightly_export": "una exportación nocturna empieza antes de hora en varias cuentas",
    "partner_sync": "la sincronización de un socio se reinició sin backoff",
    "scraper_reset": "un scraper sincroniza sus ráfagas con el reinicio de la ventana",
    "load_test": "una prueba de carga apuntada a producción por error",
    "retry_loop": "el bucle de reintentos de un cliente, sin espera",
    "sdk_retry_bug": "una versión del SDK con un bug en los reintentos",
    "mobile_polls": "una actualización de la app móvil consulta a ráfagas",
    "webhook_replay": "un webhook mal configurado repite toda su cola",
}

STAGES = [
    StageText("Sin límite",
              "Reto: unos pocos clientes inundan la API y el resto falla con ellos. Limita a cada uno.",
              "Etapa 1: cuenta las peticiones de cada cliente por ventana de 1 s"),
    StageText("Ventana fija",
              "Reto: una ventana fija deja pasar el doble si una ráfaga cruza el reinicio. Suavízala.",
              "Etapa 2: cambia la ventana por un token bucket"),
    StageText("Token bucket",
              "Reto: cada cliente tiene su tope, pero juntos aún saturan el backend. Repártelo.",
              "Etapa 3: limita a cada cliente a su parte justa de la capacidad"),
    StageText("Bucket + reparto justo",
              "Resuelto: cada cliente recibe una parte suave y justa; una avalancha no daña al resto.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "deja pasar el tráfico normal"),
    "limited": GoalText("Limitada ≥ 50%", "limita cada cliente por seg."),
    "peak": GoalText("Pico ≤ 1.6x", "usa un token bucket"),
    "others": GoalText("Resto servido ≥ 99%", "da a cada uno su parte justa"),
    "served": GoalText("Servidas ≥ 99%", "deja de limitar en calma"),
}

LEGEND = {"idle": "en reposo", "normal": "normal", "flooding": "en avalancha", "limited": "limitada",
          "failed": "fallida", "served": "servida", "limit": "límite", "flood": "avalancha"}

STRINGS = {
    # el dibujo de clúster: clientes -> limitador -> backend
    "pic_state": "limitador → backend: {state}",
    # incidentes
    "who_one": "1 cliente",
    "who_many": "{n} clientes",
    "flooded": "recibe una avalancha de {who}: {cause}",
    "calm_again": "vuelve la calma",
    "warn_503": "el backend da 503",
    # el panel
    "tile_load": "Carga",
    "tile_others": "Resto",
    "tile_peak": "Pico",
    "bar_clients": "Clientes",
    "bar_backend": "Backend",
    "requests": "Peticiones",
    "limit": "límite {limit:.0f}/s",
    "head_flood": "{n} en avalancha: backend a {sent}/s",
    "head_calm": "Backend: {sent}/s de {capacity:.0f}/s",
    "stat_limited": "limitadas",
    "note_chart": "Gráfica: peticiones por segundo que llegan al backend.",
    # errores en tu código
    "stuck": "una petición lleva más de {seconds:.0f} s: ¿RateLimiter.allow espera algo?",
}

LESSON = Lesson(
    title="Limitación de tráfico",
    one_liner="Unos pocos clientes ruidosos pueden tumbar una API para todos. Un rate limiter mantiene a cada uno en su parte.",
    learn=(
        "Sin límite, un backend reparte su capacidad entre quien más grita. Un proceso por lotes, un "
        "scraper o un bucle de reintentos en unas pocas cuentas llena la cola, y las peticiones de "
        "todos los demás clientes fallan con las suyas.",
        "Ventana fija: cuenta las peticiones de cada cliente por segundo (o por minuto) y rechaza el "
        "resto. Es simple y barata, pero una ráfaga al final de una ventana y al principio de la "
        "siguiente deja pasar el doble del límite en un momento.",
        "Token bucket: cada cliente tiene un cubo que se rellena al ritmo permitido, hasta un tamaño "
        "de ráfaga; cada petición gasta un token. No hay bordes que aprovechar, y las ráfagas cortas "
        "siguen siendo posibles.",
        "Un límite por cliente es una promesa a cada cliente. Súmalas y pueden prometer mucho más de "
        "lo que el backend puede hacer. Un reparto justo limita a cada cliente a capacidad / clientes "
        "activos, así nunca se promete al backend más de lo que tiene.",
    ),
    watch_for=(
        "Sin límite: durante una avalancha el backend rechaza peticiones (rojo), y los clientes que no "
        "hicieron nada mal también fallan.",
        "Ventana fija: la avalancha tiene tope, pero su pico llega al doble del límite cuando una ráfaga "
        "cruza un reinicio.",
        "Token bucket: el pico es suave, pero varios clientes con tope siguen saturando el backend juntos.",
        "Reparto justo: los clientes en avalancha son rechazados (naranja oscuro) y el resto es servido.",
    ),
    build=(
        ("Redis: un token bucket compartido por muchos servidores de la API (un script atómico por petición)",
         "local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens') or ARGV[2])\n"
         "local last = tonumber(redis.call('HGET', KEYS[1], 'last') or ARGV[3])\n"
         "tokens = math.min(ARGV[2], tokens + (ARGV[3] - last) * ARGV[1])\n"
         "local ok = tokens >= 1\n"
         "if ok then tokens = tokens - 1 end\n"
         "redis.call('HSET', KEYS[1], 'tokens', tokens, 'last', ARGV[3])\n"
         "return ok"),
        ("NGINX: un leaky bucket por IP de cliente",
         "limit_req_zone $binary_remote_addr zone=api:10m rate=20r/s;\n"
         "location /api/ { limit_req zone=api burst=10 nodelay; }"),
    ),
    checklist=(
        "Limita por cliente (API key, cuenta, IP), no solo de forma global.",
        "Usa un token bucket o una ventana deslizante, no una ventana fija sin más.",
        "Devuelve 429 con Retry-After, para que los clientes que se portan bien esperen.",
        "Asegúrate de que los límites por cliente no sumen más de lo que el backend puede hacer.",
        "Limita en el borde (gateway) y en el servicio, y alerta sobre la proporción de 429.",
    ),
    refs=(
        Ref("Stripe: Scaling your API with rate limiters",
            "https://stripe.com/blog/rate-limiters",
            "Limitadores de peticiones y de concurrencia y load shedders, como los usa Stripe (en inglés)."),
        Ref("Cloudflare: How we built rate limiting capable of scaling to millions of domains",
            "https://blog.cloudflare.com/counting-things-a-lot-of-different-things/",
            "Por qué las ventanas fijas dejan pasar ráfagas, y una ventana deslizante barata (en inglés)."),
        Ref("Token bucket (Wikipedia)",
            "https://en.wikipedia.org/wiki/Token_bucket",
            "El algoritmo, y su relación con el leaky bucket (en inglés)."),
        Ref("NGINX: Rate Limiting with NGINX",
            "https://blog.nginx.org/blog/rate-limiting-nginx",
            "limit_req, burst y nodelay, con ejemplos (en inglés)."),
        Ref("Envoy: global rate limiting",
            "https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/other_features/global_rate_limiting",
            "Token buckets locales en cada proxy más un servicio de límites compartido (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/rate_limiting/es/main.py y mira cómo se rechaza la avalancha.",
        "Haz la etapa 2 y mira cómo el objetivo Pico se pone verde.",
        "Haz la etapa 3 y mira cómo el resto de clientes sigue al 100% durante una avalancha.",
    ),
)

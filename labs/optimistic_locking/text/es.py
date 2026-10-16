"""Laboratorio optimistic_locking, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Bloqueo optimista"
SUMMARY = "Muchas peticiones leen, cambian y escriben las mismas filas. No pierdas ningún cambio, y atiéndelas."
PARAMS = {"rate": "compras por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"flash": "OFERTA", "import": "CARGA", "slow": "LENTO", "calm": "CALMA"}
CAUSES = {
    "flash_sale": "abre una oferta relámpago de un producto",
    "push_alert": "una notificación lleva a todo el mundo a un producto",
    "influencer": "una influencer enlaza un producto ante millones",
    "price_error": "un error de precio deja un producto casi gratis",
    "supplier_feed": "se importa de golpe el inventario del proveedor",
    "recount": "se carga un recuento del almacén con la tienda abierta",
    "price_sync": "un proceso nocturno de sincronización reescribe los artículos populares",
    "cross_az": "los servidores pasan a otra zona, lejos de la base de datos",
    "packet_loss": "un switch averiado pierde paquetes; cada ida y vuelta se retransmite",
    "db_cpu": "un informe desbocado satura la CPU de la base de datos",
    "noisy_neighbour": "un vecino ruidoso satura la máquina de la base de datos",
}

STAGES = [
    StageText("Gana la última escritura",
              "Reto: dos peticiones leen una fila y ambas escriben; un cambio se pierde. Mira la versión.",
              "Etapa 1: escribe con compare_and_set y lanza Conflict"),
    StageText("Control de versión",
              "Reto: nada se pierde, pero las filas muy usadas responden 409. Relee, combina y reintenta.",
              "Etapa 2: relee y reintenta con backoff, jitter y tope"),
    StageText("Reintento y combinación",
              "Resuelto: ningún cambio perdido, y se atiende incluso la fila más usada.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "adjust() debe devolver"),
    "lost": GoalText("Perdidos = 0", "usa compare_and_set"),
    "conflicts": GoalText("409 ≤ 1%", "reintenta: relee y combina"),
    "fast": GoalText("p99 < 500ms", "pon tope al backoff"),
    "served": GoalText("Servidas ≥ 98%", "reintenta hasta MAX_TRIES"),
}

LEGEND = {"idle": "en reposo", "first_try": "primer intento", "retries": "reintento 1,2,3",
          "conflict": "conflicto (409)", "lost": "cambio perdido", "served": "servida",
          "limit": "usuarios/s", "incident": "incidente"}

STRINGS = {
    # incidentes
    "flash_start": "{times:.1f}x el tráfico, casi todo a un artículo, en tandas: {cause}",
    "flash_end": "la oferta ha terminado",
    "import_start": "un proceso escribe {rate:.0f} filas/s en los artículos populares: {cause}",
    "import_end": "la carga ha terminado",
    "slow_start": "cada consulta tarda {ms:.0f} ms: {cause}",
    "slow_end": "la base de datos vuelve a ir rápido",
    "warn_lost": "{n} cambios perdidos",
    # valores de los objetivos
    "count": "{n}",
    # el panel
    "tile_lost": "Perdidos",
    "tile_conflicts": "409",
    "tile_retried": "Reint.",
    "bar_users": "Usuarios",
    "bar_writes": "Escrituras",
    "limit": "usuarios/s",
    "head_lost": "{n} cambios perdidos en 10 s",
    "head_conflicts": "{n} respuestas 409 en 10 s",
    "head_flash": "Oferta: casi todo a una fila",
    "head_import": "Una carga escribe filas populares",
    "head_slow": "BD lenta: ventana de carrera mayor",
    "head_ok": "Ningún cambio perdido",
    # los dibujos
    "state_lost": "CAMBIOS PERDIDOS",
    "state_conflicts": "CONFLICTOS",
    "state_hot": "FILA CALIENTE",
    "state_slow": "LENTO",
    "pic_state": "3 servidores → BD de inventario: {state}",
    "note": "Los puntos son una muestra de escrituras, más lentas (decorativo).",
    "subtitle": "por segundo, último 1 s",
    "title": "Escrituras",
    # errores en tu código
    "stuck": "una petición lleva más de {seconds:.0f} s: ¿adjust() llega a devolver algo?",
}

LESSON = Lesson(
    title="Bloqueo optimista",
    one_liner="Leer, cambiar, escribir: si dos peticiones lo hacen a la vez en la misma fila, la segunda "
              "escritura borra la primera.",
    learn=(
        "Un leer-modificar-escribir (lee el inventario, resta 2, escríbelo) son dos idas y vueltas. Otra "
        "petición puede escribir la misma fila entre medias; entonces escribes un valor calculado con "
        "datos viejos, y su cambio desaparece. Es la actualización perdida: ningún error, solo un número "
        "equivocado.",
        "El bloqueo optimista da a cada fila una versión. Escribes con la versión que leíste: "
        "UPDATE ... SET value = $new, version = version + 1 WHERE id = $id AND version = $read. Una "
        "sola sentencia comprueba y escribe a la vez. Si no coincide con ninguna fila, alguien llegó "
        "antes: es un conflicto, y no se ha sobrescrito nada.",
        "Un conflicto no anula lo que el usuario quería. Vuelve a leer la fila, aplica el cambio al valor "
        "nuevo (la combinación) e inténtalo otra vez. Espera antes un tiempo pequeño y aleatorio (jitter): "
        "las peticiones que perdieron la misma carrera se enteran juntas, y si reintentan enseguida leen la "
        "misma versión nueva y vuelven a chocar, un ganador por ronda, mientras sus escrituras fallidas "
        "hacen cola en la fila. Haz que la espera crezca en cada intento, y pon tope a las esperas y a los "
        "intentos.",
        "Es optimista porque apuesta a que los conflictos son raros: nadie retiene un bloqueo mientras "
        "piensa. Cuando una fila está muy caliente (una oferta relámpago), los conflictos son frecuentes; "
        "los reintentos siguen funcionando, pero SELECT ... FOR UPDATE, un UPDATE atómico "
        "stock = stock - 2 o una cola por artículo pueden atenderla mejor.",
        "Un bloqueo dentro de tu proceso no sirve: los otros servidores no lo ven. La comprobación tiene "
        "que hacerse donde están los datos.",
    ),
    watch_for=(
        "Gana la última escritura: todas las peticiones se atienden, rápido, y la oferta pierde casi todos "
        "sus cambios (rojo).",
        "Control de versión: no se pierde nada, pero solo gana un comprador por tanda; más de la mitad "
        "recibe un 409 (naranja).",
        "Reintento y combinación: los reintentos (puntos naranjas) ganan al siguiente intento o al otro; "
        "cambios perdidos y 409 se quedan en 0.",
    ),
    build=(
        ("SQL: una columna de versión y una actualización condicional",
         "UPDATE stock SET value = $1, version = version + 1\n"
         "WHERE id = $2 AND version = $3;\n"
         "-- 0 filas actualizadas: alguien escribió desde que leíste -> relee y reintenta"),
        ("Python: reintento con jitter completo",
         "for attempt in range(MAX_TRIES):\n"
         "    if attempt:\n"
         "        await asyncio.sleep(random.uniform(0, min(CAP, BASE * 2 ** attempt)))\n"
         "    row = await db.read(item)\n"
         "    if await db.compare_and_set(item, row.value + delta, row.version):\n"
         "        return\n"
         "raise Conflict(item)  # 409"),
        ("HTTP: ETag e If-Match",
         "GET /items/42          -> ETag: \"v17\"\n"
         "PUT /items/42  If-Match: \"v17\"\n"
         "-> 412 Precondition Failed si alguien lo cambió antes"),
    ),
    checklist=(
        "Cada fila que se lee, se cambia y se vuelve a escribir tiene una versión (o una marca de tiempo, o un ETag).",
        "Las escrituras comprueban la versión en la misma sentencia que escribe: nunca comprobar y luego escribir.",
        "Ante un conflicto, vuelve a leer y aplica de nuevo el cambio; nunca reintentes el valor viejo.",
        "Los reintentos esperan un tiempo aleatorio pequeño que crece, con tope en la espera y en los intentos.",
        "Cuenta los conflictos: una tasa alta indica una fila caliente, que quizá pida otro diseño.",
        "Responde 409 (o 412) cuando te rindas, para que el cliente sepa que no se cambió nada.",
    ),
    refs=(
        Ref("Martin Fowler: Optimistic Offline Lock",
            "https://martinfowler.com/eaaCatalog/optimisticOfflineLock.html",
            "El patrón: detectar un conflicto con una versión y deshacer la transacción (en inglés)."),
        Ref("PostgreSQL: Transaction isolation",
            "https://www.postgresql.org/docs/current/transaction-iso.html",
            "Por qué dos leer-modificar-escribir en Read Committed pueden perder un cambio (en inglés)."),
        Ref("AWS: Optimistic locking with version number (DynamoDB)",
            "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBMapper.OptimisticLocking.html",
            "Escrituras condicionales sobre un atributo de versión (en inglés)."),
        Ref("AWS Architecture Blog: Exponential backoff and jitter",
            "https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/",
            "Por qué el jitter completo hace que los clientes que compiten terminen antes (en inglés)."),
        Ref("Wikipedia: Control de concurrencia optimista",
            "https://es.wikipedia.org/wiki/Control_de_concurrencia_optimista",
            "Las fases de lectura, validación y escritura."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/optimistic_locking/es/main.py y mira cómo los cambios perdidos rojos pasan a ser 409 naranjas.",
        "Luego mira la próxima oferta relámpago: ¿cuántos compradores del artículo reciben un error?",
        "Haz la etapa 2 y mira cómo desaparecen los 409 sin perder ningún cambio.",
    ),
)

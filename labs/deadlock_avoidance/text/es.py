"""Laboratorio deadlock_avoidance, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Evitar interbloqueos"
SUMMARY = "Cada transferencia bloquea dos cuentas. Que nunca se esperen unas a otras en círculo."
PARAMS = {"rate": "transferencias por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"payout": "PAGOS", "refunds": "REEMB.", "slow": "LENTO", "batch": "LOTE", "calm": "CALMA"}
CAUSES = {
    "month_end": "el pago de fin de mes liquida a todos los comercios a la vez",
    "weekly_payout": "el pago semanal empieza en pleno pico de ventas",
    "instant_payouts": "una función nueva de pagos al instante envía el dinero en cuanto llega",
    "reserve_release": "se liberan las reservas retenidas a los comercios",
    "cancelled_sale": "se cancela una venta relámpago: se reembolsa cada pedido mientras los compradores siguen comprando",
    "double_charge": "un error cobró dos veces; soporte reembolsa a compradores que siguen comprando",
    "event_cancelled": "se cancela un concierto: el vendedor de entradas reembolsa a sus compradores",
    "chargebacks": "una red de tarjetas envía una ola de contracargos contra un comercio",
    "audit_disk": "el disco del registro de auditoría se atasca de vez en cuando",
    "audit_failover": "la base de datos de auditoría pasa a su réplica",
    "audit_compaction": "el almacén de auditoría compacta sus archivos a mediodía",
    "audit_backup": "una copia de seguridad congela el volumen del almacén de auditoría",
    "fee_sweep": "el cobro nocturno de comisiones se retrasa y coincide con el tráfico del día",
    "interest": "se abonan intereses a los comercios, muchas cuentas por proceso",
    "reconciliation": "la conciliación bancaria corrige muchos saldos a la vez",
    "fx_settlement": "la liquidación de divisas mueve dinero entre muchas cuentas a la vez",
}

STAGES = [
    StageText("Orden de la petición",
              "Reto: A→B y B→A se esperan para siempre y el servicio se congela. Añade timeouts.",
              "Etapa 1: timeout, libera todo, backoff y reintento"),
    StageText("Timeouts y reintento",
              "Reto: ya no se congela, pero hay timeouts, reintentos y esperas. Bloquea en un orden.",
              "Etapa 2: bloquea por id creciente; audita tras liberar"),
    StageText("Un solo orden",
              "Resuelto: ningún interbloqueo puede formarse, todo va rápido y no se pierde dinero.",
              "Todas las etapas hechas"),
]

GOALS = {
    "deadlocks": GoalText("Interbloqueos = 0", "bloquea en un orden global"),
    "completed": GoalText("Completadas ≥ 99%", "timeout, libera, reintenta"),
    "p99": GoalText("p99 ≤ 100ms", "suelta pronto los bloqueos"),
    "retries": GoalText("Reintentos ≤ 0,1", "en orden: sin timeouts"),
    "money": GoalText("Descuadre = 0 $", "mueve con ambos bloqueos"),
}

LEGEND = {"idle": "en reposo", "first_try": "primer intento", "retries": "reintento, espera más",
          "done": "hecha", "deadlock": "interbloqueo, fallo", "account": "cuenta", "incident": "incidente"}

STRINGS = {
    # incidentes
    "payout_start": "{rate:.0f} pagos/s entre las cuentas más activas, en ambos sentidos, y a vendedores: {cause}",
    "payout_end": "el pago masivo ha terminado",
    "refunds_start": "{rate:.0f} reembolsos/s de un gran comercio a compradores que le siguen pagando: {cause}",
    "refunds_end": "los reembolsos han terminado",
    "slow_start": "el {rate:.1f}% de las escrituras de auditoría se atasca 0,2-0,6 s: {cause}",
    "slow_end": "el registro de auditoría vuelve a ir rápido",
    "batch_start": "{rate:.0f} lotes/s, cada uno bloquea de 10 a 25 cuentas: {cause}",
    "batch_end": "el proceso por lotes ha terminado",
    "warn_frozen": "{n} interbloqueos que nadie rompió; el más largo duró {seconds:.1f} s",
    "warn_broken": "{n} interbloqueos, cada uno roto por un timeout de bloqueo",
    "warn_retries": "{n} reintentos tras timeouts de bloqueo",
    # valores de los objetivos
    "count": "{n}",
    "money": "{amount} $",
    # el panel
    "tile_deadlocks": "Interbl.",
    "tile_p99": "p99",
    "tile_retries": "Reint.",
    "bar_asked": "Pedidas",
    "bar_done": "Hechas",
    "bar_retries": "Reint.",
    "title": "Transferencias",
    "head_deadlock": "Interbloqueo x{n}: espera circular",
    "head_frozen": "Congelado: sin workers libres",
    "head_retries": "{n} reintentos en 1 s",
    "head_payout": "Pago masivo: en ambos sentidos",
    "head_refunds": "Reembolsos: flujo al revés",
    "head_slow": "Escrituras de auditoría lentas",
    "head_batch": "Lotes que bloquean muchas cuentas",
    "head_ok": "Todas obtienen sus bloqueos",
    # los dibujos
    "state_deadlock": "INTERBLOQUEO x{n}",
    "state_frozen": "CONGELADO: SIN WORKERS",
    "state_waiting": "{n} ESPERAN BLOQUEOS",
    "state_payout": "PAGO MASIVO",
    "state_refunds": "REEMBOLSOS",
    "state_slow": "AUDITORÍA LENTA",
    "state_batch": "LOTES",
    "pic_state": "{n} esperan: {state}",
    "note": "Los puntos son una muestra de transferencias, más lentas (decorativo).",
}

LESSON = Lesson(
    title="Evitar interbloqueos",
    one_liner="Dos transferencias que bloquean las mismas dos cuentas en orden contrario pueden esperarse "
              "para siempre; un orden global de bloqueo lo hace imposible.",
    learn=(
        "Una transferencia bloquea las dos cuentas para que nadie las escriba en medio. Si las bloquea "
        "en el orden de la petición (origen y luego destino), A→B y B→A pueden obtener cada una su primer "
        "bloqueo y esperar el de la otra: un interbloqueo. Hacen falta cuatro cosas (Coffman, 1971): "
        "bloqueos exclusivos, retener uno mientras esperas otro, que nadie te lo quite, y que las esperas "
        "formen un ciclo.",
        "Sin un detector de interbloqueos, las dos transferencias esperan para siempre. Peor aún: cada "
        "transferencia que toca A o B espera detrás de ellas reteniendo su propio primer bloqueo, y la "
        "pila llega a las cuentas más activas hasta que todos los workers del servicio quedan "
        "atascados: se congela.",
        "Los timeouts de bloqueo rompen el retener y esperar: abandona una espera tras poco tiempo, "
        "libera todo, espera un backoff con jitter y vuelve a intentarlo. Nada se congela, pero cada "
        "timeout tira trabajo, y con mucha contención también salta en esperas que solo eran largas. Los "
        "reintentos añaden carga, y sin jitter dos transferencias que chocaron reintentan a la vez y "
        "vuelven a chocar (un bloqueo activo, livelock en inglés).",
        "Un orden global de bloqueo rompe el ciclo: bloquea siempre las cuentas por id ascendente. Un "
        "ciclo exigiría que alguien esperara un id menor reteniendo uno mayor, y nadie lo hace. Un "
        "proceso por lotes bloquea todas sus cuentas en ese orden antes de mover nada. Deja un timeout "
        "largo solo como red de seguridad.",
        "El orden evita interbloqueos, no esperas: un bloqueo retenido más tiempo hace esperar más a todos "
        "los de detrás. Mantén corta la sección crítica: las comprobaciones, las lecturas y el trabajo "
        "lento (el registro de auditoría, una llamada a otro servicio) van fuera de los bloqueos.",
        "Las bases de datos también lo hacen: PostgreSQL y MySQL detectan un interbloqueo y matan una "
        "transacción (el cliente recibe un error y reintenta). Bloquea las filas en un orden coherente "
        "(por clave primaria) y nunca tendrán que hacerlo.",
    ),
    watch_for=(
        "Orden de la petición: durante el pago masivo, un ciclo rojo en el dibujo del clúster; luego la "
        "puerta se cierra y el indicador del servidor se llena: todos los workers están atascados.",
        "Timeouts y reintento: aparecen ciclos que se rompen en una fracción de segundo, pero los "
        "reintentos naranjas llenan los carriles, y el p99 y los reintentos pasan sus límites.",
        "Un solo orden: nunca se forma un ciclo; las flechas entre cuentas son cortas y blancas.",
    ),
    build=(
        ("Python: un solo orden de bloqueo",
         "for account in sorted({src, dst}):\n"
         "    await locks.acquire(account, timeout=2.0)   # solo una red de seguridad\n"
         "try:\n"
         "    await ledger.move(src, dst, amount)\n"
         "finally:\n"
         "    locks.release_all()\n"
         "await audit.record(entries)                     # trabajo lento, tras los bloqueos"),
        ("SQL: bloquea las dos filas por id",
         "BEGIN;\n"
         "SELECT id FROM accounts WHERE id IN ($1, $2) ORDER BY id FOR UPDATE;\n"
         "UPDATE accounts SET balance = balance - $3 WHERE id = $1;\n"
         "UPDATE accounts SET balance = balance + $3 WHERE id = $2;\n"
         "COMMIT;"),
        ("PostgreSQL: una red de seguridad para las esperas",
         "SET lock_timeout = '2s';        -- abandona la espera de un bloqueo (SQLSTATE 55P03)\n"
         "SET deadlock_timeout = '1s';    -- cuánto espera antes de buscar interbloqueos"),
    ),
    checklist=(
        "Todo código que toma más de un bloqueo los toma en el mismo orden global (por id).",
        "Un lote toma todos sus bloqueos al principio, en ese orden, antes de cambiar nada.",
        "Nada lento ocurre con un bloqueo retenido: ni llamadas de red, ni auditoría, ni esperar al usuario.",
        "Las esperas de bloqueo tienen un timeout como red de seguridad; al vencer, libera todo antes de "
        "reintentar.",
        "Los reintentos esperan un backoff con jitter, unas pocas veces como mucho.",
        "Cuenta los interbloqueos, el tiempo esperando bloqueos y los timeouts, y alerta con ellos.",
    ),
    refs=(
        Ref("Wikipedia: Interbloqueo",
            "https://es.wikipedia.org/wiki/Bloqueo_mutuo",
            "Las cuatro condiciones de Coffman, y cómo prevenirlo, evitarlo y detectarlo."),
        Ref("PostgreSQL: Explicit locking, deadlocks",
            "https://www.postgresql.org/docs/current/explicit-locking.html",
            "Interbloqueos: «adquiere los bloqueos de varios objetos en un orden coherente» (en inglés)."),
        Ref("MySQL: How to minimize and handle deadlocks",
            "https://dev.mysql.com/doc/refman/8.0/en/innodb-deadlocks-handling.html",
            "Transacciones cortas, un orden coherente y reintentar la víctima (en inglés)."),
        Ref("MySQL: Deadlock detection",
            "https://dev.mysql.com/doc/refman/8.0/en/innodb-deadlock-detection.html",
            "innodb_deadlock_detect, y por qué los servidores con mucha carga lo apagan (en inglés)."),
        Ref("Linux kernel: lockdep",
            "https://www.kernel.org/doc/html/latest/locking/lockdep-design.html",
            "Un validador que comprueba que cada bloqueo se toma siempre en el mismo orden (en inglés)."),
        Ref("AWS Builders' Library: Timeouts, retries and backoff with jitter",
            "https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/",
            "Por qué los reintentos necesitan backoff y jitter (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/deadlock_avoidance/es/main.py y mira cómo el congelamiento se vuelve reintentos.",
        "Cambia al dibujo del clúster (v) durante el pago masivo: aparecen ciclos y se rompen.",
        "Haz la etapa 2 y mira cómo los ciclos desaparecen para siempre.",
    ),
)

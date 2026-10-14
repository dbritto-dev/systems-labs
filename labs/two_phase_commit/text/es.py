"""Laboratorio two_phase_commit, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Consolidación en dos fases"
SUMMARY = "Una transferencia toca 3 fragmentos. Consolídala en todos, o en ninguno."
PARAMS = {"rate": "transferencias por segundo"}

INCIDENT = IncidentText("Incidente", "el incidente", "el próximo incidente")
VERBS = {"overload": "LENTO", "refuse": "NO", "shard_crash": "CAÍDA", "coord_crash": "CAÍDA", "partition": "CORTE",
         "back": "VUELVE", "heal": "UNIDA", "calm": "CALMA"}
CAUSES = {
    "report_oom": "un informe largo bloquea filas en n2; las transferencias se acumulan en la memoria del coordinador",
    "report_locks": "un informe largo retiene bloqueos de filas: las preparaciones dan timeout de bloqueo",
    "check_constraint": "una migración añade una restricción CHECK que algunas filas no cumplen",
    "frozen_accounts": "cumplimiento normativo congela un lote de cuentas",
    "shard_oom": "el sistema mata al fragmento por falta de memoria justo después de votar sí",
    "kernel_panic": "un pánico del kernel justo después de votar sí",
    "host_reboot": "su máquina se reinicia por un parche del kernel, a mitad de la transacción",
    "coord_oom": "el sistema mata al coordinador por falta de memoria mientras envía una consolidación",
    "deploy": "un despliegue mata al coordinador sin vaciarlo antes",
    "node_evicted": "desalojan el nodo del coordinador por mantenimiento",
    "switch_port": "falla un puerto del switch entre el coordinador y el fragmento",
    "firewall_rule": "un cambio en el firewall bloquea el puerto del fragmento",
    "bgp_flap": "una inestabilidad de BGP corta la ruta a la zona del fragmento",
}

STAGES = [
    StageText("Un fragmento a la vez",
              "Reto: un fragmento dice que no a mitad y los demás conservan sus escrituras. Usa 2PC.",
              "Etapa 1: prepara en todos, consolida solo si todos votan sí"),
    StageText("Consolidación en dos fases",
              "Reto: las caídas dejan transferencias en duda, con filas bloqueadas. Registra y recupera.",
              "Etapa 2: registra la consolidación antes de enviarla; los fragmentos preguntan"),
    StageText("2PC con recuperación",
              "Resuelto: cada transferencia se consolida en todos los fragmentos o en ninguno.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("Base correcta", "deben consolidarse"),
    "rolled": GoalText("Abortos limpios 100%", "prepara; consolida o aborta"),
    "partial": GoalText("Parciales = 0", "consolida solo si todos sí"),
    "money": GoalText("Dinero conservado", "registra antes; reenvía"),
    "doubt": GoalText("En duda ≤ 3s tras", "pregunta; reenvía al volver"),
    "completed": GoalText("Completas ≥ 90% tras", "libera bloqueos: resuelve"),
}

LEGEND = {"prepare": "preparar", "yes": "vota sí", "commit": "consolidar", "abort": "no / abortar",
          "ask": "pregunta", "doubt": "en duda", "partial": "parcial", "limit": "transferencias",
          "incident": "incidente"}

STRINGS = {
    # incidentes
    "overload_start": "{shard} va lento: el {share:.0%} de las preparaciones dan timeout de bloqueo: {cause}",
    "overload_end": "{shard} vuelve a responder a tiempo",
    "refuse_start": "{shard} vota no en el {share:.0%} de las transferencias: {cause}",
    "refuse_end": "{shard} vuelve a votar sí",
    "shard_crash_start": "{shard} se cae: {cause}",
    "shard_crash_end": "{shard} vuelve, con sus transferencias preparadas y sus bloqueos",
    "coord_crash_start": "el coordinador se cae: {cause}",
    "coord_crash_end": "el coordinador vuelve; se ejecuta recover()",
    "partition_start": "{shard} queda aislado del coordinador: {cause}",
    "partition_end": "{shard} vuelve a hablar con el coordinador",
    "warn_crash": "el coordinador se queda sin memoria mientras envía una consolidación",
    "warn_blocked": "filas preparadas siguieron bloqueadas en duda hasta {seconds:.1f} s",
    "warn_partial": "{n} transferencias consolidadas solo en algunos fragmentos",
    "warn_stuck": "{n} transferencias siguen en duda: sus filas siguen bloqueadas",
    # valores de los objetivos
    "none": "ninguno",
    # el panel
    "tile_partial": "Parciales",
    "tile_money": "Dinero",
    "tile_doubt": "En duda",
    "bar_votes": "Votos",
    "bar_decided": "Decisiones",
    "bar_ended": "Terminan",
    "limit": "transferencias",
    "head_partial": "{n} parciales en 10 s",
    "head_down": "Coordinador caído: {n} en duda",
    "head_doubt": "{n} en duda: filas bloqueadas",
    "head_failing": "Votan no: se aborta",
    "head_ok": "Cada transferencia es atómica",
    # los dibujos
    "state_partial": "PARCIAL",
    "state_down": "COORDINADOR CAÍDO",
    "state_doubt": "EN DUDA",
    "state_shard_down": "FRAGMENTO CAÍDO",
    "state_no": "VOTAN NO",
    "pic_state": "n0 → n1 · n2 · n3: {state}",
    "note": "Los puntos son una muestra de mensajes, más lentos (estético).",
    "subtitle": "por segundo, último 1 s",
    "title": "Protocolo",
}

LESSON = Lesson(
    title="Consolidación en dos fases",
    one_liner="Una transacción, varios fragmentos: todos la consolidan o ninguno, aunque un fragmento "
              "diga que no, un nodo se caiga o se pierdan mensajes.",
    learn=(
        "Escribir en cada fragmento por turnos no es atómico: cuando un fragmento posterior dice que no "
        "(un timeout de bloqueo, una restricción) o se cae, los anteriores conservan sus escrituras. "
        "Una transferencia que cobró al cliente pero nunca pagó al comercio ha destruido dinero.",
        "La consolidación en dos fases parte la transacción en dos. Fase 1, preparar: cada fragmento "
        "bloquea sus filas, las comprueba y escribe un registro de preparación en disco, y luego vota. "
        "Un sí es una promesa: podrá consolidar pase lo que pase, incluso tras una caída. Fase 2: solo "
        "si todos votan sí, el coordinador envía consolidar; si no, abortar.",
        "Entre su sí y la decisión, un fragmento está en duda: no puede consolidar (otros quizá votaron "
        "no) ni abortar (el coordinador quizá decidió consolidar). Tiene que mantener sus bloqueos y "
        "esperar. Es el precio de 2PC: mientras el coordinador está caído, las filas preparadas siguen "
        "bloqueadas y frenan cada transacción que las necesite.",
        "Por eso la decisión tiene que sobrevivir al coordinador: escribe 'commit' en su registro antes "
        "de enviarlo (esa escritura es el punto de consolidación), lo reenvía hasta que cada fragmento lo "
        "confirma, y tras reiniciar vuelve a enviar lo que tenga el registro. Un fragmento en duda "
        "pregunta hasta saber el resultado. Con aborto presunto, una transacción que el registro no "
        "conoce nunca se consolidó: se aborta.",
    ),
    watch_for=(
        "Un fragmento a la vez: cuando n2 dice que no, n1 ya tiene la escritura: una consolidación "
        "parcial (rojo) y dinero creado o destruido.",
        "Consolidación en dos fases: los votos no abortan limpiamente, pero la caída del coordinador "
        "deja fragmentos en duda (naranja) para siempre, con bloqueos, y las transferencias siguientes "
        "dan timeout en esas filas.",
        "2PC con recuperación: los fragmentos siguen en duda mientras el coordinador está caído (el "
        "precio honesto), y se resuelven un momento después de que vuelva.",
    ),
    build=(
        ("PostgreSQL: cada fragmento prepara, el coordinador decide",
         "BEGIN; UPDATE accounts SET balance = balance - 30 WHERE id = 'c17';\n"
         "PREPARE TRANSACTION 't42';          -- el voto: duradero, mantiene los bloqueos\n"
         "COMMIT PREPARED 't42';              -- o ROLLBACK PREPARED 't42'\n"
         "SELECT gid, prepared FROM pg_prepared_xacts;   -- en duda tras un reinicio"),
        ("MySQL / XA: las mismas dos fases entre gestores de recursos",
         "XA START 't42'; UPDATE accounts ...; XA END 't42';\n"
         "XA PREPARE 't42';\n"
         "XA COMMIT 't42';                    -- XA RECOVER lista las que están en duda"),
        ("El coordinador: la decisión es duradera antes de que nadie la oiga",
         "votes = await gather(*(prepare(s) for s in shards))\n"
         "if all(votes): await log.write(txn, 'commit')   # el punto de consolidación\n"
         "for s in shards: retry_until_ack(s, decision)\n"
         "# al reiniciar: reenvía cada commit del registro; txn desconocida -> abort"),
    ),
    checklist=(
        "Un fragmento vota sí solo cuando su registro de preparación (y los bloqueos) están en disco.",
        "Consolida solo si todos los fragmentos votaron sí; un voto que no llega es un no.",
        "Registra la decisión de consolidar antes de enviarla, y reenvíala hasta que cada fragmento la confirme.",
        "Un fragmento preparado nunca decide solo: pregunta al coordinador hasta saber el resultado.",
        "Aborto presunto: una transacción sin registro de consolidación no se consolidó.",
        "Alerta si hay transacciones en duda mucho tiempo: retienen bloqueos (pg_prepared_xacts, XA RECOVER).",
    ),
    refs=(
        Ref("Martin Kleppmann: Designing Data-Intensive Applications, cap. 9",
            "https://dataintensive.net/",
            "Consolidación atómica y en dos fases, la caída del coordinador y las transacciones en duda "
            "(en inglés)."),
        Ref("PostgreSQL: PREPARE TRANSACTION",
            "https://www.postgresql.org/docs/current/sql-prepare-transaction.html",
            "El lado del participante en 2PC, y por qué no hay que dejar transacciones preparadas "
            "(en inglés)."),
        Ref("Martin Kleppmann: Transactions: myths, surprises and opportunities",
            "https://martin.kleppmann.com/2015/09/26/transactions-at-strange-loop.html",
            "Una charla sobre lo que de verdad significa ACID, transacciones distribuidas incluidas "
            "(en inglés)."),
        Ref("Wikipedia: Commit de dos fases",
            "https://es.wikipedia.org/wiki/Commit_de_dos_fases",
            "El protocolo, su problema de bloqueo, y el aborto presunto."),
        Ref("Princeton COS 418: Two-phase commit",
            "https://www.cs.princeton.edu/courses/archive/fall16/cos418/docs/L6-2pc.pdf",
            "Diapositivas: el protocolo paso a paso, y qué hacer ante timeouts y fallos (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/two_phase_commit/es/main.py y mira cómo los votos no abortan en cada fragmento.",
        "Luego mira la caída del coordinador: ¿qué fragmentos se quedan en naranja, y por qué no pueden decidir?",
        "Haz la etapa 2 y mira cómo los fragmentos en duda se resuelven un momento después de que vuelva el coordinador.",
    ),
)

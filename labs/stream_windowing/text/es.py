"""Laboratorio stream_windowing, en español: cada palabra que muestra. Mismos nombres y claves que en.py."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Ventanas en un flujo"
SUMMARY = "Cuenta compras por ventana de 10 s con eventos tardíos y desordenados: tiempo del evento, marca de agua, retraso."
PARAMS = {"rate": "compras (eventos) por segundo"}

INCIDENT = IncidentText("Datos tardíos", "los datos tardíos", "los próximos datos tardíos")
VERBS = {"offline": "LOTE", "lag": "ATRASO", "skew": "RELOJ", "backfill": "REPITE", "calm": "CALMA"}
CAUSES = {
    # teléfonos que vuelven a tener conexión
    "subway": "los pasajeros salen del metro y sus teléfonos se sincronizan",
    "flight_mode": "los teléfonos salen del modo avión tras aterrizar",
    "app_suspended": "el sistema había suspendido la app; ahora vacía su cola",
    "carrier_outage": "termina una caída de un operador móvil",
    # una partición se atrasa
    "broker_gc": "una pausa larga de GC en el broker de la partición",
    "slow_disk": "un disco lento en el líder de la partición",
    "rebalance": "un reequilibrio del grupo de consumidores",
    "hot_partition": "una clave caliente satura la partición",
    # el reloj de un productor va atrasado
    "ntp_down": "un grupo de productores no llega al servidor NTP",
    "vm_resume": "máquinas virtuales reanudadas tras una pausa con el reloj viejo",
    "bad_rtc": "un lote de dispositivos con el reloj de hardware defectuoso",
    "container_clock": "una imagen de contenedor con la zona horaria mal configurada",
    # una recarga de datos
    "replay": "se reenvían eventos que perdió un error en un servicio anterior",
    "partner_upload": "un socio sube sus ventas de los últimos minutos",
    "mirror_catchup": "una réplica de otra región se pone al día",
    "restore": "eventos recuperados del archivo tras una caída",
}

STAGES = [
    StageText("Tiempo de proceso",
              "Reto: las ventanas cuentan al llegar, así que lo tardío cae en la ventana equivocada.",
              "Etapa 1: tiempo del evento con marca de agua"),
    StageText("Tiempo del evento + marca",
              "Reto: en calma todo cuadra, pero lo que llega tras cerrar la ventana se descarta.",
              "Etapa 2: retraso permitido, correcciones, salida lateral"),
    StageText("Retraso permitido + correcciones",
              "Resuelto: lo tardío corrige su ventana; lo que llega aún más tarde va a la salida lateral.",
              "Todas las etapas hechas"),
]

GOALS = {
    "baseline": GoalText("En calma ≥99.9%", "cuenta por tiempo del evento"),
    "exact": GoalText("Exactas ≥99%", "guarda ventanas, corrige"),
    "dropped": GoalText("Descartados = 0", "salida lateral, no descartes"),
    "latency": GoalText("Latencia p99 ≤5s", "emite con la marca de agua"),
    "state": GoalText("Estado ≤6 ventanas", "expulsa las ya vencidas"),
}

LEGEND = {"idle": "en reposo", "on_time": "a tiempo", "late": "tardío (más = más tarde)", "counted": "contado",
          "updated": "contado tarde (corrección)", "side": "salida lateral",
          "dropped": "descartado / otra ventana", "incident": "incidente"}

STRINGS = {
    "note_dots": "Los puntos son una muestra, más lentos (decorativo).",
    "note_chart": "La gráfica: eventos por segundo según lo que hizo con ellos el procesador.",
    # incidentes
    "title_offline": "Lote tardío",
    "title_lag": "Partición atrasada",
    "title_skew": "Reloj desfasado",
    "title_backfill": "Recarga",
    "offline_start": "los teléfonos envían eventos de hasta {seconds:.0f} s atrás: {cause}",
    "offline_end": "ya llegaron los lotes pendientes",
    "lag_start": "la partición {partition} va {seconds:.0f} s atrasada: {cause}",
    "lag_end": "la partición se puso al día",
    "skew_start": "el reloj de un productor va {seconds:.0f} s atrasado: {cause}",
    "skew_end": "el reloj vuelve a estar en hora",
    "backfill_start": "una recarga envía eventos de hasta {minutes:.0f} min atrás: {cause}",
    "backfill_end": "terminó la recarga",
    "warn_dropped": "se descartaron {n} eventos tardíos",
    "warn_wrong": "{n} eventos se contaron en la ventana equivocada",
    # el estado bajo el dibujo
    "state": "marca de agua {wm} · estado {n}/{max}",
    "state_none": "aún no hay eventos",
    # el panel
    "tile_exact": "Exactas",
    "tile_dropped": "Descartes",
    "tile_latency": "Latencia",
    "bars": "Ventanas",
    "bars_sub": "por tiempo del evento",
    "head_dropped": "Se descartan eventos tardíos",
    "head_wrong": "Lo tardío cae en otra ventana",
    "head_side": "Lo muy tardío va a salida lateral",
    "head_updated": "Lo tardío corrige su ventana",
    "head_state": "El estado no para de crecer",
    "head_offline": "Está llegando un lote tardío",
    "head_lag": "Una partición va atrasada",
    "head_skew": "Un reloj de productor va atrasado",
    "head_backfill": "Una recarga reenvía lo viejo",
    "head_edges": "Rezagados caen en otra ventana",
    "head_calm": "Los eventos llegan a tiempo",
    "stat_counted": "contados",
    "stat_updates": "correcciones",
    "stat_side": "lateral",
    "stat_dropped": "descartados",
    "stat_late": "demora p99",
}

LESSON = Lesson(
    title="Ventanas en un flujo",
    one_liner="Cuenta según cuándo pasó, espera un poco y sigue corrigiendo: una marca de agua más un retraso permitido.",
    learn=(
        "Un procesador de flujos cuenta compras por ventana de 10 segundos para un panel en vivo. "
        "Cada evento lleva su tiempo del evento (cuándo ocurrió la compra); llega al procesador más "
        "tarde, a través de un log con particiones: normalmente en menos de un segundo y algo "
        "desordenado, pero a veces mucho después (teléfonos que estaban sin conexión, una partición "
        "atrasada, un productor con el reloj atrasado, una recarga de datos).",
        "El tiempo de proceso, la ventana abierta cuando el evento LLEGA, es fácil y rápido pero "
        "incorrecto: un rezagado cerca del final de una ventana cae en la siguiente, y un lote "
        "tardío cae entero en la ventana actual. Los totales por ventana fallan justo cuando importa.",
        "Tiempo del evento con marca de agua: pon cada evento en la ventana de su propia marca de "
        "tiempo, y decide cuándo una ventana está completa con una marca de agua: el mayor tiempo del "
        "evento visto menos una cota del desorden (2 s aquí). Cuando la marca de agua pasa el final de "
        "una ventana, emítela. Los eventos detrás de la marca de agua son tardíos: descartarlos "
        "mantiene las ventanas pequeñas y los resultados rápidos, pero pierde datos sin avisar.",
        "Retraso permitido: guarda cada ventana cerrada un rato más (30 s en tiempo de la marca de agua) y, cuando "
        "un evento tardío cae en ella, emite la cuenta corregida: el panel muestra una corrección. Lo "
        "que llega aún más tarde va a una salida lateral (un topic de mensajes muertos) para que un "
        "proceso por lotes lo concilie, así que nada se descarta sin avisar; y las ventanas que pasan "
        "su retraso se expulsan, así que el estado no crece. Esperar más antes del primer resultado "
        "también sería correcto, pero demasiado lento para un panel en vivo.",
    ),
    watch_for=(
        "Tiempo de proceso: rojo en la puerta incluso en calma (rezagados), y mucho en un lote tardío.",
        "Tiempo del evento + marca: las ventanas en calma cuadran, pero un lote tardío cierra la puerta: rojo, descartado.",
        "Retraso permitido: lo tardío se vuelve azul (correcciones), lo muy viejo morado (salida lateral); el indicador sigue bajo.",
    ),
    build=(
        ("Flink: una marca de agua con desorden acotado, retraso permitido y una salida lateral para lo más tardío",
         "events.assignTimestampsAndWatermarks(\n"
         "    WatermarkStrategy.<Purchase>forBoundedOutOfOrderness(Duration.ofSeconds(2))\n"
         "        .withTimestampAssigner((p, ts) -> p.eventTime))\n"
         "  .keyBy(p -> p.shop)\n"
         "  .window(TumblingEventTimeWindows.of(Duration.ofSeconds(10)))\n"
         "  .allowedLateness(Duration.ofSeconds(30))\n"
         "  .sideOutputLateData(tooLate)\n"
         "  .aggregate(new CountPurchases());"),
        ("Kafka Streams: un periodo de gracia; los registros tardíos corrigen la cuenta de la ventana",
         "purchases.groupByKey()\n"
         "  .windowedBy(TimeWindows.ofSizeAndGrace(Duration.ofSeconds(10), Duration.ofSeconds(30)))\n"
         "  .count();"),
        ("Spark Structured Streaming: la marca de agua acota el estado; el modo update reemite ventanas",
         "(events.withWatermark(\"event_time\", \"30 seconds\")\n"
         "   .groupBy(window(\"event_time\", \"10 seconds\")).count()\n"
         "   .writeStream.outputMode(\"update\"))"),
    ),
    checklist=(
        "Agrupa en ventanas por tiempo del evento, nunca por tiempo de llegada, para todo lo que reportes o factures.",
        "Fija la marca de agua según el desorden que mides (p99 de llegada menos tiempo del evento), no a ojo.",
        "Permite el retraso que esperas y haz que el destino acepte correcciones (upsert por ventana).",
        "Manda lo que llegue aún más tarde a una salida lateral y alerta según su ritmo: nunca lo descartes sin avisar.",
        "Expulsa las ventanas que pasan su retraso, y vigila el tamaño del estado y el tiempo hasta el primer resultado.",
    ),
    refs=(
        Ref("Apache Flink: Timely Stream Processing",
            "https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/time/",
            "Tiempo del evento, tiempo de proceso y marcas de agua (en inglés)."),
        Ref("Apache Flink: Windows",
            "https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/operators/windows/",
            "Ventanas fijas, retraso permitido, y los datos tardíos como salida lateral (en inglés)."),
        Ref("The Dataflow Model (VLDB 2015)",
            "https://www.vldb.org/pvldb/vol8/p1792-Akidau.pdf",
            "El artículo detrás de las marcas de agua, los disparadores y las correcciones por datos tardíos (en inglés)."),
        Ref("Apache Beam: Watermarks and late data",
            "https://beam.apache.org/documentation/programming-guide/#watermarks-and-late-data",
            "Marcas de agua, retraso permitido y disparadores que vuelven a emitir con datos tardíos (en inglés)."),
        Ref("Spark Structured Streaming: Handling late data and watermarking",
            "https://spark.apache.org/docs/latest/streaming/apis-on-dataframes-and-datasets.html",
            "withWatermark, agregaciones por ventana, y cómo la marca de agua acota el estado (en inglés)."),
        Ref("Confluent: Kafka Streams concepts",
            "https://docs.confluent.io/platform/current/streams/concepts.html",
            "Tiempo del evento, ventanas y periodos de gracia para registros desordenados (en inglés)."),
    ),
    try_next=(
        "Haz la etapa 1 en labs/stream_windowing/es/main.py y mira cómo cuadran las ventanas en calma.",
        "Haz la etapa 2 y mira cómo lo tardío se vuelve azul (correcciones) en vez de rojo.",
        "Pon ALLOWED_DELAY = 32.0 en vez de permitir retraso: ¿por qué falla la latencia?",
        "Quita evict() en la etapa 2: ¿qué le pasa al indicador, y al estado?",
    ),
)

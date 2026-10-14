# Laboratorio: consolidación en dos fases

*[Read in English](../README.md)*

Un banco guarda sus cuentas en 3 fragmentos (`n1`, `n2`, `n3`) en una red simulada (~30 ms por
mensaje); el coordinador es `n0`. Los clientes envían ~10 transferencias por segundo. Cada
transferencia toca los tres fragmentos: quita dinero a un cliente en uno, paga a un comercio en otro
y la comisión del banco en el tercero, y las tres cantidades suman cero. Hay pocos comercios y pocas
cuentas de comisiones, así que sus filas están muy disputadas: una fila que se queda bloqueada frena
las transferencias que vienen detrás.

Los incidentes llegan al azar, como en producción: un fragmento vota no en una parte de las
transferencias (timeouts de bloqueo detrás de un informe largo, una restricción CHECK nueva, cuentas
congeladas), un fragmento se cae justo después de votar sí (vuelve con su disco: los registros de
preparación y sus bloqueos), el coordinador se cae (un despliegue o un desalojo lo matan al
instante; la falta de memoria lo mata mientras envía una consolidación, así que un fragmento recibe
la decisión y los demás no), o la red aísla un fragmento del coordinador. La ejecución nunca se
reinicia. El primer incidente siempre es `n2` lento con timeouts de bloqueo de 0:20 a 0:30; a las
0:26 el sistema mata al coordinador, lleno de transferencias en espera, por falta de memoria
mientras envía una consolidación, y vuelve a las 0:29.

```
LABS_LANG=es uv run python -m live two_phase_commit          # míralo; edita es/main.py y guarda
LABS_LANG=es uv run python -m live two_phase_commit --lesson # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/two_phase_commit             # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves (primer incidente) |
|---|---|---|
| 0 Un fragmento a la vez (dada) | escribe en cada fragmento por turnos; para en el primer no | cuando `n2` dice que no, el fragmento anterior conserva su escritura: 22 consolidaciones parciales, $2,773 creados o destruidos (rojo) |
| 1 Consolidación en dos fases | `two_phase`: prepara en todos (`vote`), consolida solo si todos votan sí, si no aborta; los fragmentos `prepare` / `commit` / `abort` | los votos no abortan en todos los fragmentos; pero la caída deja a `n2` y `n3` en duda para siempre (naranja), faltan $121, y sus filas bloqueadas hacen que las transferencias siguientes den timeout (56% completas) |
| 2 2PC con recuperación | registra la consolidación antes de enviarla, reenvíala hasta que se confirme, `recover()` reenvía lo que tenga el registro; los fragmentos en duda preguntan (`ask`) al coordinador; `on_status` responde desde el registro (aborto presunto) | los fragmentos siguen en duda mientras el coordinador está caído (el precio de 2PC), y se resuelven un momento después de que vuelva; todos los objetivos OK |

Objetivos, juzgados por incidente (transferencias que empezaron desde 1 s antes, porque siguen en
marcha cuando empieza): base correcta (≥ 95% consolidadas en los 15 s anteriores), abortos limpios
100% (las transferencias a las que un fragmento dijo que no no se aplican en ninguno; "ninguno" si
ningún fragmento dijo que no), parciales = 0 (aplicadas en algunos fragmentos y abortadas en otros),
dinero conservado 3 s después de que termine (el dinero creado o destruido por sus transferencias:
$0), en duda ≤ 3 s después de que termine (transferencias preparadas que aún esperan una decisión),
y completas ≥ 90% de las transferencias que empiezan en los 5 s siguientes.

- **Por qué un fragmento no puede decidir solo.** Cuando ya votó sí, los demás quizá consolidaron
  (el coordinador registró la consolidación y la envió a un fragmento antes de caerse). Un fragmento
  que aborta tras un timeout deja esa transferencia a medias. Tiene que mantener sus bloqueos y
  preguntar.
- **Por qué registrar antes de enviar.** Si el coordinador envía la consolidación y se cae antes de
  registrarla, un coordinador nuevo no encuentra nada y responde "abort" (aborto presunto) a los
  fragmentos que preguntan: el que recibió la consolidación la conserva y los demás abortan. A
  medias otra vez.
- **El precio.** Mientras el coordinador está caído, las filas preparadas siguen bloqueadas: el
  indicador "En duda" está en naranja y los eventos muestran cuánto tiempo estuvieron retenidas.
  2PC es seguro, no disponible.

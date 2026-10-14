# Laboratorio: peticiones de respaldo

*[Read in English](../README.md)*

Los usuarios envían ~100 lecturas/s a través de tu `Client`. Cada clave está en 3 réplicas,
y cualquiera puede responder. Una respuesta tarda ~10 ms (p95 ~14 ms), pero 1 de cada 50
tarda 100–400 ms de todos modos: una pausa de GC, un fallo de caché, un disco lento. Es raro
para una llamada, pero es justo lo que ve el usuario del p99. En momentos al azar, como en
producción, una réplica se vuelve mucho más lenta durante un rato, 0.2–0.8 s por respuesta
(una compactación, un vecino ruidoso, un volumen degradado, una instantánea de copia de
seguridad), o todas se vuelven varias veces más lentas (una clave caliente, cachés en frío
tras un despliegue). Los usuarios se rinden a 1 s. El primer incidente siempre es la
réplica 2, 0.5 s por respuesta, entre 0:20 y 0:30.

```
uv run python -m live hedged_requests --lang es            # míralo; edita es/main.py y guarda
uv run python -m live hedged_requests --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/hedged_requests            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Una llamada (dada) | pregunta a una réplica y espera lo que haga falta | p99 ~150–270 ms sin que nada falle: lo marcan las respuestas lentas raras |
| 1 Copia | tras `HEDGE_AFTER` (20 ms) sin respuesta, manda una copia a otra réplica; gana la primera respuesta | p99 ~30 ms, con ~2% más de llamadas; pero una réplica lenta cuesta una copia por cada lectura que le llega (+35%; +100% si van lentas todas), y sus perdedoras siguen en curso (~85% de su tiempo perdido) |
| 2 Copia + presupuesto + cancelar | un `HedgeBudget` (5% de las lecturas, 10 tokens) paga cada copia; cancela la perdedora | las copias se quedan en +6–7% en cualquier incidente, sin nada perdido; mientras una réplica sigue lenta, las lecturas que le llegan esperan (el precio del presupuesto) |

Objetivos, evaluados en cada lentitud: p99 ≤ 50 ms (antes); llamadas extra ≤ 10% de las
lecturas (durante); tiempo de las réplicas perdido en llamadas que nadie espera ≤ 5%
(durante); servidas ≥ 99% (durante); p99 ≤ 50 ms otra vez desde 3 s después de que acabe
(después, así que el presupuesto debe rellenarse).

La gráfica muestra las copias enviadas cada segundo, frente al 10% del tráfico.

**Dos dibujos.** Se abre con **clúster**: el servicio (donde corre tu `Client`) y las 3
réplicas. Las lecturas vuelan en blanco; las llamadas vuelan a una réplica, en blanco la
primera y en naranja una copia. Una llamada que tarda se queda junto a su réplica, en naranja
claro mientras su lectura la espera, y en naranja intenso cuando la otra copia ya respondió y
nadie la canceló: trabajo perdido. Una réplica lenta se pone naranja. Pulsa `v` (o
`--view lanes`) para ver **carriles**: los usuarios se ponen naranja claro mientras su
lectura va lenta y naranja cuando se manda una copia (puntos naranjas grandes vuelan a la
puerta); la puerta es el presupuesto de copias, cerrada mientras las lecturas lentas se
quedan sin copia, y el indicador son las llamadas por lectura.

# Laboratorio: hashing consistente

*[Read in English](../README.md)*

Los usuarios leen ~500 claves/s (que varían despacio; unas pocas claves son mucho más
populares que el resto) de 8 servidores de caché que están delante de una base de datos lenta
(10 ms por lectura, 4 a la vez: unas 400 lecturas/s). Tu `Router.node_for(key)` elige el
servidor de cada lectura; un acierto responde al momento, un fallo va a la base de datos y
llena la caché de ese servidor. En momentos al azar, como en producción, el clúster cambia:
se cae un nodo (un kernel panic, la nube recupera una instancia spot, se queda sin memoria…) y más tarde se
sustituye por uno con la caché vacía, el autoescalado añade un noveno nodo durante un rato, o
un despliegue reinicia uno. La ejecución nunca se reinicia. El primer cambio siempre es un
nodo que se cae a las 0:20.

```
uv run python -m live consistent_hashing --lang es            # míralo; edita es/main.py y guarda
uv run python -m live consistent_hashing --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/consistent_hashing            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Módulo (dada) | `hash(key) % N` | un cambio mueve ~7/N de las claves: los fallos ponen los puntos en rojo, los aciertos bajan a ~60% de antes, la base de datos lee ~2.5x |
| 1 Anillo de hash | un punto por nodo en un anillo; una clave va al siguiente punto en el sentido de las agujas del reloj | un cambio mueve ~1/N, pero el nodo más cargado tiene 1.9x la media |
| 2 Anillo + nodos virtuales | 200 puntos por nodo | se mueve ~1/N, el nodo más cargado tiene 1.16x; todos los objetivos OK |

Objetivos, evaluados en cada cambio:

- **Claves/nodo ≤ 1.4x** (antes): claves del nodo más cargado frente a la media, en el clúster
  tal como estaba justo antes del cambio.
- **Movidas ≤ 3/N** (durante): de 2,000 claves de muestra, cuántas van a otro nodo después del
  cambio, en unidades de 1/N (N es el clúster más grande). Lo ideal es 1/N; con módulo es ~7/N.
  Un anillo con un punto por nodo puede mover hasta ~2.5/N cuando sale un nodo con un arco grande.
- **Aciertos ≥ 90%** (después): la tasa de aciertos en los 4 s después del cambio frente a los
  15 s de antes.
- **Carga BD ≤ 2x** (después): lecturas/s a la base de datos en los 4 s después del cambio
  frente a los 15 s de antes.

La etapa sale del primer cambio: las claves movidas y el reparto, que decide tu enrutador. Los
aciertos y la carga de la base de datos son lo que notan los usuarios y la base de datos; vienen
después.

Cada cambio se mide donde ocurre: el escenario le pregunta a tu enrutador adónde van las claves de
muestra justo antes y justo después de `add` o `remove`. Usa un hash estable (`stable_hash`,
md5): el `hash()` de Python para un string cambia de un proceso a otro.

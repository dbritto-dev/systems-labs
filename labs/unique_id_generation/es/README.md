# Laboratorio: IDs únicos (Gossip Glomers #1-2 de Fly.io)

*[Read in English](../README.md)*

Los retos #1 (Echo) y #2 (Unique ID Generation) de [Gossip Glomers](https://fly.io/dist-sys/),
en Python, sobre una red simulada: 5 nodos, ~100 ms por mensaje. Los clientes envían `echo` y
`generate` a nodos al azar. Los incidentes llegan al azar, como en producción: la red entre los
nodos se parte, el reloj de un nodo se atrasa (NTP), o una migración de VM hace las dos cosas.
El primero siempre es una migración entre 0:20 y 0:30.

```
uv run python -m live unique_id_generation --lang es            # míralo; edita es/main.py y guarda
uv run python -m live unique_id_generation --lang es --lesson   # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/unique_id_generation            # x = aún no, X = hecho
```

Dos dibujos: `cluster` (el de siempre: los nodos y los mensajes entre ellos) y `lanes`
(lo que ven los clientes: sus peticiones esperando, la red como una puerta, el clúster como
un solo servidor). Pulsa `v` para cambiar, o empieza con `--view lanes`.

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Nada aún (dada) | sin manejadores | cada petición recibe un error |
| 1 Echo | `on_echo` responde `echo_ok` | echo funciona; aún sin IDs (un contador por nodo da duplicados; preguntar a un líder se detiene en una partición) |
| 2 IDs únicos | `on_generate`: nodo + contador | únicos y disponibles, pero no una clave de 64 bits ordenable |
| 3 IDs Snowflake | ms \| nodo \| secuencia, sin ir nunca atrás | únicos, de 64 bits, ordenados por tiempo, aguantan los saltos de reloj |

Objetivos, evaluados en cada incidente: echo funciona; ningún ID duplicado (15 s antes y
durante el incidente); `generate` responde ≥ 99% durante el incidente; los IDs son enteros de
64 bits y van ordenados por tiempo (un ID es mayor que todos los entregados al menos 1 s antes)
en la calma previa; los IDs de ningún nodo van hacia atrás durante el incidente.

Cada nodo lee su reloj de pared con `self.wall_ms()`; el escenario puede atrasarlo.

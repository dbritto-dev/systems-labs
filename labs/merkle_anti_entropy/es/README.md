# Laboratorio: antientropía con árboles de Merkle

*[Read in English](../README.md)*

Réplicas que se separan sin avisar, en Python sobre una red simulada: 4 réplicas (n0 ... n3) de un
almacén clave/valor, cada una con una copia completa de las mismas 20,000 claves, ~100 ms por
mensaje. Los clientes escriben ~100 claves por segundo, cada una en una réplica, que la replica a
las demás por lotes cada 0.1 s; y leen ~200 claves por segundo de cualquier réplica en pie, la
mitad claves escritas hace poco. La replicación pierde escrituras de vez en cuando, y nadie te
avisa. Los incidentes llegan al azar, como en producción: una réplica está caída más tiempo del
que cubren sus pistas (las demás guardan como mucho 50 pistas cada una para ella, y las escrituras
que no caben nunca le llegan), un corte de red pierde los lotes de replicación de y hacia una
réplica, un disco dañado pierde unos cientos de claves en una réplica, o un operador restaura una
copia vieja sobre un rango de claves de una réplica. El primer incidente siempre es la caída de n2,
de 0:20 a 0:30.

```
uv run python -m live merkle_anti_entropy --lang es            # míralo; edita es/main.py y guarda
uv run python -m live merkle_anti_entropy --lang es --lesson   # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/merkle_anti_entropy            # x = todavía no, X = hecho
```

| Etapa | En `es/main.py` | Qué ves |
|---|---|---|
| 0 Sin reparación (dada) | solo replicación | tras un incidente una réplica se queda naranja para siempre, y las lecturas que caen en ella reciben versiones viejas |
| 1 Barrido completo | `diff`, `full_scan`, `sync_keys`, `on_scan`: en cada ronda, envía a un par la versión de cada clave; toma lo que tiene más nuevo, envía lo que pide | las réplicas vuelven a azul en segundos, pero la gráfica es un muro naranja: 20,000 entradas por ronda para hallar unos cientos de diferencias |
| 2 Árboles de Merkle | `MerkleTree` (actualizado en `changed`), `merkle_sync`, `on_hashes`: compara raíces, baja solo donde los hash difieren, sincroniza las claves de las hojas que difieren | una ronda en calma cuesta unos pocos cientos de entradas; tras un incidente una ráfaga corta naranja lo repara |

Objetivos, evaluados por incidente: cada clave que difiere reparada como mucho 15 s después de que
acaba el incidente; como mucho un 0.2% de lecturas viejas en los 10 s siguientes; como mucho 150
entradas de reparación enviadas por clave reparada (desde que empieza el incidente hasta 15 s
después de que acaba); y como mucho 10,000 unidades de cálculo de hash por segundo en la réplica
más ocupada (en los 15 s anteriores al incidente).

Una clave *difiere* en una réplica que tiene una versión más vieja que la última (o ninguna); las
escrituras de hace menos de 0.5 s aún se están replicando y no cuentan. Una lectura es *vieja*
cuando devuelve una versión anterior a la última. Un mensaje cuesta sus *entradas*: una por
elemento de cada lista, tupla, conjunto o dict de su cuerpo (una clave con su versión, un hash, un
índice de nodo), más una. El *cálculo de hash* es una unidad por cada parte que pasa por
`self.digest`.

El árbol: el nivel 0 es la raíz, el nivel `DEPTH` las `16 ** DEPTH` hojas, cada una un tramo
seguido del rango de claves. El hash de una hoja es el XOR de los digest de sus claves, así que un
cambio cuesta dos digest (fuera el viejo, dentro el nuevo); el hash de un nodo interior es el
digest de los hash de sus hijos, recalculado solo para los ancestros de las hojas que cambiaron.
El tamaño de hoja lo eliges tú: con `DEPTH = 1` cada hoja tiene 1,250 claves, y una clave mala las
envía todas; con `DEPTH = 3` una hoja tiene ~5 claves. Reconstruir el árbol con todos los datos en
cada ronda (como la compactación de validación de Cassandra) es barato en la red pero calcula el
hash de 20,000 claves cada vez.

Incluso en calma las raíces casi nunca coinciden: algunas escrituras aún van de camino entre
réplicas. Por eso una ronda de Merkle en calma igualmente baja por el árbol y cuesta unos cientos
de entradas, y por eso Envío cuenta toda la ventana.

Cómo habla tu nodo está en `core/net.py`; lo que recibe una réplica (sus datos, `store`,
`changed`, `digest`, la replicación y las pistas) está en `api.py`.

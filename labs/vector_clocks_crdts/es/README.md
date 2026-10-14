# Laboratorio: relojes vectoriales y CRDT

*[Read in English](../README.md)*

Replicación con varios líderes de carritos de compra, en Python sobre una red simulada: 5
réplicas, una por sitio, ~100 ms por mensaje. Cada réplica acepta al momento las altas y bajas
de los dispositivos cercanos (sin líder, funciona sin conexión) y difunde sus carritos a las
demás. Un carrito lo comparten dos dispositivos que hablan con dos réplicas distintas, así que
el mismo carrito se edita en dos sitios a la vez. Los incidentes llegan al azar, como en
producción: la red parte las réplicas en dos (los dos lados siguen aceptando escrituras), una
réplica queda aislada de las demás (su sitio sigue atendiendo, y vuelve con carritos viejos más
sus propios cambios), o el reloj de una réplica salta adelante o atrás (un ajuste de NTP) y sus
marcas de tiempo mienten. El primer incidente siempre separa {n0, n1} de {n2, n3, n4} de 0:20 a
0:30.

```
uv run python -m live vector_clocks_crdts --lang es            # míralo; edita es/main.py y guarda
uv run python -m live vector_clocks_crdts --lang es --lesson   # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/vector_clocks_crdts            # x = todavía no, X = hecho
```

| Etapa | En `es/main.py` | Qué ves |
|---|---|---|
| 0 Gana la última escritura (dada) | cada carrito es un valor con la hora del reloj; gana la marca más nueva | cuando la red se une, las altas de un lado desaparecen; un salto de reloj pierde altas sin ninguna partición |
| 1 Relojes vectoriales | `compare`, `keep_newest`: las versiones concurrentes son hermanas, fusionadas (una unión) al leer | no se pierde ningún alta, pero vuelven productos quitados desde una hermana que aún los tenía |
| 2 CRDT | `ORSet`: una etiqueta única por alta, una baja pone lápida a las etiquetas que ha visto, fusionar es unir | las réplicas divergen durante el corte y coinciden un segundo después de unirse; nada perdido, nada revivido |

Objetivos, juzgados por incidente: altas perdidas = 0 y bajas revividas = 0 (desde que empieza
el incidente hasta 10 s después de que acaba), ≥ 99% de los carritos iguales en todas las
réplicas 5 s después de que acaba, y como mucho 150 mensajes por segundo entre réplicas (en los
15 s anteriores).

Un alta se *pierde* cuando la réplica que la confirmó ya no tiene el producto mientras el
dispositivo aún lo tiene en el carrito; una baja *revive* cuando el producto aparece otra vez en
la réplica que confirmó la baja. Cada dispositivo añade y quita solo sus propios productos (6 de
los 12 del carrito), alternando: un producto quitado a menudo se vuelve a añadir más tarde, así
que las lápidas tienen que ser por alta (una etiqueta), no por producto. Un carrito está *igual*
cuando `items(cart)` coincide en las 5 réplicas; el comprobador mira cada 250 ms, desde fuera
de la red, y se salta los carritos escritos en el último segundo.

Cómo habla tu nodo está en `core/net.py`: `self.reply`, `self.send`, `self.every` y los
manejadores `on_<tipo>`. El código dado ya envía cada cambio a cada par y difunde todos los
carritos una vez por segundo: tú cambias cómo se guarda, se escribe y se fusiona un carrito
(`items`, `add`, `remove`, `put`, `state`, `merge`).

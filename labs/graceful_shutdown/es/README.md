# Laboratorio: apagado ordenado

*[Read in English](../README.md)*

Los usuarios mandan ~300 peticiones/s (con una deriva lenta) a **6 instancias** de una
aplicación tras un **balanceador de carga** de 3 nodos. El balanceador deja pasar las
conexiones: elige una instancia, por turnos, solo cuando un cliente abre una conexión. El 60%
de las peticiones llegan por conexiones que los clientes mantienen abiertas (**conexiones
persistentes**), y los usuarios tienen ~100 **flujos** abiertos (WebSockets, eventos enviados
por el servidor) durante minutos. Cada nodo del balanceador comprueba si cada instancia está
lista cada **2 s**, la saca de la rotación tras **3 comprobaciones fallidas** seguidas, y
necesita **1 s** más para aplicarlo. Una conexión enviada a una instancia que no escucha se
rechaza: un error.

En momentos al azar, como en producción, se paran instancias: un **despliegue gradual**
reemplaza las 6 una a una (una versión nueva, un cambio de configuración, una imagen base
parcheada, una vuelta atrás), se **drena un nodo** (un parche del núcleo, una actualización de
nodos, una instancia spot reclamada con 2 minutos de aviso) o el **autoescalado quita una
instancia**. Cada vez el orquestador manda **SIGTERM**, arranca la sustituta (arranca en 4 s;
entonces la siguiente instancia vieja recibe SIGTERM) y mata a la vieja con **SIGKILL a los
30 s** de SIGTERM. Tu `on_sigterm(server)` decide qué pasa entre medias. El primer incidente
es siempre un despliegue gradual a las 0:20. La ejecución nunca se reinicia.

```
uv run python -m live graceful_shutdown --lang es            # míralo; edita es/main.py y guarda
uv run python -m live graceful_shutdown --lang es --lesson   # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/graceful_shutdown            # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Salir de golpe (dada) | `server.exit()` | ~50 peticiones y flujos cortados por instancia (~290 por despliegue), y durante 5-7 s el balanceador aún manda 1 de cada 6 conexiones nuevas a una instancia que ya no está: ~10% de errores; cuando la siguiente instancia para antes de que la nueva esté en rotación, solo sirven 4 de 6 |
| 1 Drenar | `drain(server, deadline)`: deja de aceptar, cierra las conexiones ociosas, espera a lo que está en curso (con un plazo), sal | no se corta nada, cada instancia sale en ~4 s, pero su socket cerrado rechaza lo que el balanceador aún manda: sigue habiendo ~10% de errores, 4 de 6 sirviendo |
| 2 Primero, no lista | `shutdown(server)`: deja de estar lista, espera a que el balanceador la saque, y drena | sin errores, nada cortado, 5 de 6 sirviendo, cada instancia se va en ~12 s, mucho antes de SIGKILL |

Objetivos, evaluados por incidente: base correcta (antes: ≤ 0.1% de errores), errores ≤ 0.1% de
las peticiones que empiezan durante él, peticiones y flujos cortados en curso = 0, al menos 5 de
6 instancias sirviendo (en el balanceador y aceptando) en todo momento (durante), y cada
instancia que paró salió antes de SIGKILL (después).

Por qué importa el orden: un socket cerrado no le puede decir nada al balanceador, solo puede
rechazar conexiones. La comprobación de lista es el único canal hacia el balanceador, y tarda
comprobaciones × intervalo más el retardo propio del balanceador en hacer efecto, aquí
3 × 2 s + 1 s = 7 s. Sirve con normalidad durante ese tiempo, y luego drena. Prueba a esperar
exactamente 6 s: los errores vuelven, de pocos en pocos.

**Los dibujos.** La ventana abre con los carriles: usuarios → el balanceador de carga (la puerta:
naranja mientras aún tiene una instancia que recibió SIGTERM, cerrada en rojo mientras fallan
peticiones) → la flota, cuyo indicador es cuántas de las 6 instancias sirven. Las peticiones a
una instancia vieja vuelan en naranja, las fallidas grandes y en rojo. Pulsa `v` (o
`--view cluster`) para el clúster: los 3 nodos del balanceador arriba, las 6 instancias debajo:
azul sirve, morado arranca, naranja se apaga, rojo mientras el balanceador aún le manda
conexiones que rechaza, gris cuando ya no está; las peticiones rechazadas y cortadas mueren en
rojo.

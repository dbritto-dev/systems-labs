# Laboratorio: entrega de webhooks

*[Read in English](../README.md)*

Una plataforma de tiendas envía webhooks a 20 destinos de clientes: cada pedido crea
`order.created`, luego `order.paid` (0,05–2 s después), `order.fulfilled` (4–15 s después) y a
veces `order.refunded`, ~60 eventos por segundo en total; el destino #1 es el cliente más grande.
24 workers de entrega se reparten el trabajo: un worker libre le pregunta a tu
`Dispatcher.next(now)` qué enviar, hace el POST, e informa de la respuesta con
`Dispatcher.done(ev, status, now)`. Un destino sano responde 200 en ~60 ms. En momentos al azar,
como en producción, un destino se cae (su despliegue responde 503, un certificado TLS caducado,
un servicio que se reinicia sin parar), sus conexiones se cuelgan sin respuesta (un cambio de DNS
apunta a una IP vieja, un cortafuegos descarta nuestros paquetes), se vuelve lento (su base de
datos sufre: 2,5–8 s por respuesta), responde 500 para siempre a unos pocos eventos mal formados,
o una oferta provoca un pico de 2–3 veces los eventos. La ejecución nunca se reinicia. El primer
incidente es siempre el destino #1 colgado entre 0:20 y 0:45.

```
uv run python -m live webhook_delivery --lang es          # míralo; edita es/main.py y guarda
uv run python -m live webhook_delivery --lang es --lesson # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/webhook_delivery          # x = aún no, X = hecho
```

Dos dibujos (`v` cambia): **cluster** (abre con este) muestra el despachador (a la izquierda, en
medio) entre cuatro nodos de seis workers cada uno, y los 20 destinos en cuatro columnas (#1–#5
en la primera): los intentos vuelan del despachador a un worker y a su destino, un intento que
aún espera respuesta se queda junto a su destino, las respuestas vuelven en verde (naranja
oscuro si llegan desordenadas), los fallos mueren en rojo y los eventos abandonados vuelven a la
tienda en morado. Un destino muerto es rojo, uno lento naranja. **lanes** muestra cada evento que
espera entrega como un círculo, el despachador como la puerta y los 24 workers como el servidor,
con su indicador en la parte ocupada.

| Etapa | En `main.py` | Lo que ves |
|---|---|---|
| 0 Un solo envío (dada) | una sola cola compartida; un POST que falla se abandona; sin timeout (los 30 s del cliente) | cuando #1 se cuelga, sus eventos se pierden (morado) y todos los workers acaban esperándolo: los otros 19 destinos se quedan sin servicio |
| 1 Reintentos | `timeout = ATTEMPT_TIMEOUT`; `backoff` (jitter completo, 0,5 s que se duplica, con tope de 30 s); `retry` mete cada fallo en un montículo que `next` sirve primero | nada perdido; pero los timeouts y reintentos de #1 siguen llenando el grupo compartido (el p99 de los sanos sube a segundos), y cuando un destino vuelve sus eventos llegan desordenados |
| 2 Cola por destino | `Endpoint.pick/succeeded/failed`: una cola por destino, como mucho `MAX_IN_FLIGHT` (4) POST cada uno, un evento por pedido a la vez, el más viejo primero; tras `DISABLE_AFTER` (5) fallos seguidos, pausarlo: una prueba cada 5 s con un evento nuevo, y reenviar lo atrasado cuando responda; abandonar un evento tras `MAX_ATTEMPTS` solo mientras el destino funciona (veneno) | como mucho 4 workers esperan a #1, y luego ninguno; los demás ni se enteran; todos los objetivos bien |

Objetivos, evaluados por incidente con los eventos creados durante él y 5 s después: base
correcta (antes), perdidos = 0 (eventos abandonados, o sin entregar 35 s después de la ventana;
sin contar los mal formados: nunca pueden entregarse), desordenados = 0 (un evento entregado
mientras otro anterior de su pedido seguía pendiente), el p99 de creado a entregado < 1 s para
los destinos sanos (todos menos el que tiene problemas), y trabajo perdido ≤ 10% (el tiempo de
los workers gastado en intentos que fallaron).

- **Por qué primero un timeout.** Sin él, un POST a un destino que descarta los paquetes espera
  lo que diga el cliente HTTP por defecto. Los reintentos sin timeout no pierden nada, pero cada
  intento retiene un worker 30 s.
- **Por qué aislar.** Un grupo compartido comparte la suerte: los timeouts y reintentos de un
  cliente muerto les quitan los workers a los 19 sanos. Una cola y un tope por destino (un
  mamparo) dejan el daño en su parte.
- **Por qué orden por clave, y por qué necesita una salida.** Los reintentos desordenan:
  `order.paid` sale bien mientras `order.created` espera su reintento. Un evento por pedido en
  vuelo, el más viejo primero, lo arregla; pero un evento mal formado que falla siempre bloquearía
  su pedido para siempre: abandónalo tras unos intentos, mientras el destino funcione para lo
  demás (el cliente puede reenviarlo a mano).
- **Por qué pausar.** Un destino muerto con tope sigue costando sus 4 workers en cada timeout.
  Pausarlo tras N fallos seguidos (un cortacircuitos) cuesta una prueba cada pocos segundos, y
  reenviar lo atrasado en orden cuando vuelve a responder no pierde nada.
- **No se simula, pero hazlo:** firma cada webhook con un HMAC-SHA256 de la marca de tiempo y el
  cuerpo (un secreto por destino), y manda un id de evento: la entrega «al menos una vez» quiere
  decir que un POST que agotó su timeout puede haberse procesado, y el cliente debe descartar el
  duplicado.

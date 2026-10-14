# Laboratorio: sagas

*[Read in English](../README.md)*

Los clientes hacen ~20 pedidos por segundo. Cada pedido pasa por tres servicios y no hay ninguna
transacción que los abarque, así que tu `Orchestrator` lo ejecuta como una saga: cobrar la tarjeta
(payments), reservar los artículos (stock), reservar un mensajero (shipping). Un 2% de las tarjetas
se rechazan, siempre. En momentos al azar, como en producción, una oferta relámpago agota artículos
(la reserva dice que no después de cobrar la tarjeta), la transportista tiene una caída (el envío
dice que no después de los dos), un servicio da timeout (el paso pudo hacerse o no: se perdió la
respuesta), o el propio orquestador se cae a mitad de la saga (un despliegue, falta de memoria).
Unos segundos después arranca un orquestador nuevo con los mismos servicios y el mismo registro, se
llama a `recover()` una vez, y los pedidos que llegan mientras tanto esperan en la puerta. La
ejecución nunca se reinicia. El primer incidente siempre es una transportista lenta de 0:20 a 0:30
cuyas sagas en espera hacen que el sistema mate al orquestador por falta de memoria a las 0:26
(vuelve a las 0:28).

```
LABS_LANG=es uv run python -m live saga          # míralo; edita es/main.py y guarda
LABS_LANG=es uv run python -m live saga --lesson # el concepto, enlaces y una lista de comprobación
LABS_LANG=es uv run pytest labs/saga             # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves |
|---|---|---|
| 0 Sin deshacer (dada) | cobrar, reservar, enviar; un fallo solo se detiene | clientes cobrados sin pedido, artículos retenidos para nadie (rojo); deshechos 4%, 54 a medias |
| 1 Compensaciones | ante `StepFailed`, `compensate`: deshaz los pasos cuyas refs volvieron, del último al primero | los fallos definitivos se deshacen limpiamente (naranja), pero un envío que dio timeout y sí ocurrió, y cada saga que la caída cortó, se quedan a medias |
| 2 Sagas reanudables | `key=saga_id` en cada llamada, `attempt` reintenta los timeouts, el registro dice "running" / "compensating", `recover()` reanuda cada saga sin terminar | nada a medias, ningún cobro doble, cada pedido que puede completarse se completa; todos los objetivos OK |

Objetivos, juzgados por incidente (sagas que empezaron desde 2 s antes, porque siguen en marcha
cuando empieza): base correcta (antes), deshechos 100% (las sagas que abandonaste no retienen nada
de lo que te dijeron que ocurrió; "ninguno" si no abandonaste ninguna), a medias = 0 (dinero
cobrado, artículos retenidos o un mensajero reservado para un pedido que no está completo), cobros
dobles = 0, completos ≥ 95% de los pedidos a los que nadie dijo que no, y p99 del tiempo hasta
terminar < 1 s para las sagas que empiezan en los 5 s siguientes.

- **Por qué un timeout no es un fallo.** La mitad de los timeouts pierden la respuesta, no la
  petición: el mensajero queda reservado y nunca recibiste su ref. Deshazlo por clave (deshacer lo
  que nunca pasó no hace nada), o reintenta con la misma clave y recibe la primera ref.
- **Por qué claves.** Un reintento sin clave tras una respuesta perdida vuelve a cobrar la tarjeta.
  Reanudar tras una caída repite pasos que quizá ya ocurrieron: solo las claves lo hacen seguro.
- **Por qué "compensating" en el registro.** Una saga que se cae mientras deshace debe seguir
  deshaciendo. Si el registro aún dice "running", el orquestador nuevo va hacia delante, y el cobro
  repetido (ya reembolsado) deja que el pedido salga sin pagar.

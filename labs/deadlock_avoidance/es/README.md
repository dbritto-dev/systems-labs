# Laboratorio: evitar interbloqueos

*[Read in English](../README.md)*

Los clientes les pagan a los comercios ~200 veces por segundo a través de un servicio de pagos que
ejecuta como mucho 64 transferencias a la vez (sus conexiones a la base de datos); las demás esperan
en la puerta, y un cliente se rinde a los 2 s. Cada transferencia, en tu `Payments`, bloquea las dos
cuentas (bloqueos de fila en el libro contable, mira `api.py`), mueve el dinero, escribe el registro
de auditoría (2–6 ms por fila) y libera los bloqueos. Unas pocas cuentas son las más activas: la de
custodia (#1) y la de comisiones (#2) del marketplace, y cuatro grandes comercios (#3–#6, que se
llevan una parte Zipf de todos los pagos). Como en MySQL con `innodb_deadlock_detect = OFF`, nadie
rompe un interbloqueo por ti: el servidor mata una transacción a los 8 s. En momentos al azar, como
en producción, un pago masivo mueve dinero entre las cuentas más activas en ambos sentidos (y llena
el registro de auditoría), un comercio reembolsa a los compradores que le siguen pagando
(transferencias al revés de lo habitual), la auditoría se atasca de vez en cuando (el 0,4–0,8% de
las escrituras tarda 0,2–0,6 s), o un proceso por lotes (un cobro de comisiones) bloquea de 10 a 25
cuentas a la vez. La ejecución nunca se reinicia. El primer incidente es siempre un pago masivo a
los 0:20–0:30.

```
LABS_LANG=es uv run python -m live deadlock_avoidance          # míralo; edita es/main.py y guarda
LABS_LANG=es uv run python -m live deadlock_avoidance --lesson # el concepto, enlaces y una lista
LABS_LANG=es uv run pytest labs/deadlock_avoidance             # x = aún no, X = hecho
```

| Etapa | En `es/main.py` | Lo que ves en el primer pago masivo |
|---|---|---|
| 0 Orden de la petición (dada) | `lock_all` pide `src` y luego `dst`, esperando siempre | 1–2 interbloqueos en menos de un segundo, y luego todos los workers quedan atascados: la puerta se cierra, se completa el 14–22% de las transferencias, p99 de 2 s (el timeout del cliente) |
| 1 Timeouts y reintento | `lock_all`: `timeout=0.05`; ante `LockTimeout`, `release_all()`, duerme `backoff(attempt, rng)` y reintenta hasta 8 veces | ningún interbloqueo dura (los ciclos se rompen en 50 ms), pero los timeouts también saltan en esperas largas en las cuentas más activas: 1,4–1,6 reintentos por transferencia, 88–91% completadas, p99 de 1,8–2 s |
| 2 Un solo orden | `lock_order` = `sorted(set(accounts))` en `transfer` y `settle`; auditoría tras liberar; `LOCK_TIMEOUT = 2` y 3 intentos como red de seguridad | nunca se forma un ciclo: 100% completadas, p99 de ~23 ms, 0 reintentos; todos los objetivos OK |

Objetivos, evaluados por incidente, para las transferencias que empiezan durante él: interbloqueos =
0 (un ciclo de transferencias esperando que dura 1 s), completadas ≥ 99%, p99 ≤ 100 ms (las de los
usuarios, no los lotes), reintentos ≤ 0,1 por transferencia, y descuadre = 0 $ (dinero que apareció
o desapareció porque una escritura pisó la de otra, durante el incidente y 5 s después).

Dos dibujos: `lanes` (se abre primero) muestra las transferencias como usuarios (su color: cuánto
llevan esperando), volando hacia el servicio (la puerta: blanco un primer intento, naranja un
reintento) y lo que volvió: verde hecha, rojo fallida o vencida. La puerta se cierra cuando todos
los workers están atascados; el servidor es el gestor de bloqueos y el libro contable, y su
indicador, los workers en uso. `cluster` muestra las cuentas: las seis más activas arriba
(#1–#6), y debajo seis huecos que comparten todas las demás. Una transferencia que retiene X y
espera Y es una flecha de puntos que avanzan de X a Y (blanca, luego naranja según espera); un
interbloqueo es un ciclo de flechas, en rojo; el dinero que se mueve vuela del que paga al que cobra,
en verde. Pulsa `v` para cambiar.

- **Por qué no bastan los timeouts.** Un timeout no distingue un interbloqueo de una espera larga
  en una cuenta muy usada: con contención salta en ambos, tira el trabajo, y los reintentos añaden
  carga (`TIMEOUTS`). Sin jitter, las transferencias que chocaron reintentan juntas (`NO_JITTER`);
  rendirse a la primera hace fallar el 4–5% de las transferencias (`GIVE_UP`).
- **Por qué funciona un solo orden.** Un ciclo exige una transferencia que retenga un id mayor y
  espere uno menor. Bloquear en orden nunca hace eso, ni con dos cuentas ni con un lote de 25.
- **Por qué la sección crítica debe ser corta.** El orden solo evita interbloqueos, no esperas: con
  la auditoría dentro de los bloqueos, las colas de los grandes comercios crecen (p99 de 1,4–2 s,
  `ORDER_ONLY`), y si además los timeouts son cortos, cada espera larga se vuelve un reintento
  (`ORDER_SLOW_TIMEOUT`).
- **Por qué los dos bloqueos.** Si bloqueas solo al que paga, nada espera en círculo, pero dos pagos
  al mismo comercio leen su saldo y la segunda escritura pisa la primera: aparecen o desaparecen
  ~36.000 $ en diez segundos (`PAYER_ONLY`).

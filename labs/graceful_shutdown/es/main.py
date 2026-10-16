"""Laboratorio graceful_shutdown: TU ARCHIVO. Edítalo y guarda; la ventana en vivo lo vuelve a ejecutar.

Los usuarios mandan ~300 peticiones/s a 6 instancias de una aplicación tras un balanceador
de carga. El balanceador (3 nodos) elige una instancia, por turnos, cuando un cliente abre
una conexión; el 60% de las peticiones llegan por conexiones que los clientes mantienen
abiertas (conexiones persistentes, keep-alive), y los usuarios tienen ~100 flujos abiertos
(WebSockets, eventos enviados por el servidor). Cada nodo del balanceador comprueba si cada
instancia está lista cada 2 s y la saca de la rotación tras 3 comprobaciones fallidas
seguidas, más 1 s para aplicarlo.

Los despliegues, las reducciones de escala y los drenados de nodo paran instancias: el
orquestador manda SIGTERM, arranca una sustituta (arranca en 4 s, y entonces la siguiente
instancia vieja recibe SIGTERM), y 30 s después de SIGTERM mata a la vieja (SIGKILL) esté
haciendo lo que esté haciendo. Tu `on_sigterm(server)` se ejecuta cuando una instancia recibe
SIGTERM. Ahora mismo sale de golpe: se corta cada petición y cada flujo en curso, y durante
segundos el balanceador sigue mandando conexiones nuevas a una instancia que ya no está.

Lo que `server` te deja hacer (todo en el reloj virtual: `await asyncio.sleep(s)` funciona):
  server.fail_readiness()        la comprobación de lista (GET /ready) responde 503 desde ya
  server.stop_accepting()        cierra el socket que escucha: se rechazan las conexiones nuevas
  server.close_idle()            cierra las conexiones persistentes ociosas, responde a cada
                                 petición siguiente con "Connection: close", y pide a los
                                 flujos que se reconecten (se van a otra instancia)
  await server.drained(timeout)  espera a que no quede nada en curso (True) o a que pasen
                                 `timeout` segundos (False); None espera para siempre
  server.in_flight               peticiones y flujos en curso ahora
  server.exit()                  el proceso sale; lo que siga en curso se corta
  server.health_interval (2 s), server.unhealthy_threshold (3),
  server.deregistration_delay (1 s), server.grace (30 s, de SIGTERM a SIGKILL)

Haz las etapas en orden, en este archivo:

  Etapa 1  Drenar: deja de aceptar, cierra las conexiones ociosas, espera a lo que está en
           curso (con un plazo) y sal.
  Etapa 2  Primero, no lista: haz fallar la comprobación de lista y sigue sirviendo hasta
           que el balanceador te haya sacado; luego drena.

Compruébalo:  uv run pytest labs/graceful_shutdown
Mira una solución (¡después de intentarlo!):  labs/graceful_shutdown/es/reference.py
"""

from __future__ import annotations

import asyncio  # etapa 2: await asyncio.sleep(...)


async def on_sigterm(server) -> None:
    """Se ejecuta una vez, cuando esta instancia recibe SIGTERM. Cuando termina, el proceso sale.

    Contrato:
      - Puede esperar (asyncio.sleep, server.drained) lo que quiera, pero a los
        `server.grace` segundos (30) de SIGTERM la instancia muere: lo que siga en curso
        entonces se corta, y on_sigterm se cancela.
      - El orquestador no la espera: la sustituta arranca enseguida.
    """
    # Etapa 1: en su lugar, await drain(server, server.grace - 5).
    #
    # Etapa 2: en su lugar, await shutdown(server).
    server.exit()


async def drain(server, deadline: float) -> None:
    """Etapa 1. Deja de aceptar trabajo nuevo, deja que termine lo que está en curso y sal.

    1. server.stop_accepting(): desde ahora se rechazan las conexiones nuevas.
    2. server.close_idle(): los clientes que mantienen una conexión abierta mandarían si no
       petición tras petición por ella para siempre (se cierra el socket que escucha, no su
       conexión), y los flujos duran minutos. Así todos se reconectan a otra instancia.
    3. await server.drained(deadline): espera a las peticiones en curso, como mucho
       `deadline` segundos (una petición lenta tarda hasta 5 s).
    4. server.exit().

    Luego mira: ya no se corta nada, pero el balanceador no sabe que el socket está cerrado
    hasta que fallan 3 comprobaciones seguidas. Hasta entonces sigue mandando 1 de cada 6
    conexiones nuevas a esta instancia, y cada una se rechaza: errores en la puerta. Y la
    siguiente instancia vieja recibe SIGTERM en cuanto la nueva está lista, antes de que el
    balanceador le mande nada: durante unos segundos solo sirven 4 de 6 instancias.
    """
    raise NotImplementedError("PENDIENTE etapa 1: drain")


async def shutdown(server) -> None:
    """Etapa 2. Sal primero del balanceador de carga, y luego drena.

    1. server.fail_readiness(): desde la próxima comprobación, cada nodo del balanceador
       cuenta un fallo. Sigue sirviendo todo lo que llegue mientras tanto (no dejes de
       aceptar todavía).
    2. Espera a que cada nodo del balanceador haya sacado a la instancia de la rotación:
       server.health_interval * server.unhealthy_threshold (las comprobaciones) más
       server.deregistration_delay (lo que tarda un nodo en aplicarlo), más un margen de
       alrededor de 1 s. `await asyncio.sleep(...)` (es el 'sleep' del gancho preStop).
    3. await drain(server, deadline) con un plazo que acabe bastante antes de SIGKILL:
       server.grace - lo que has esperado - unos segundos.

    Pista: esperar exactamente intervalo * umbral no basta: un nodo necesita su 1 s para
    aplicar el cambio, y las comprobaciones de cada nodo llegan cada una en su momento.
    """
    raise NotImplementedError("PENDIENTE etapa 2: shutdown")

"""Laboratorio vector_clocks_crdts: TU ARCHIVO. Edítalo y guarda; la ventana lo vuelve a ejecutar.

Carritos de compra compartidos, con varios líderes. 5 réplicas, una por sitio, en una red donde
cada mensaje tarda ~100 ms. Cada réplica acepta al momento las altas y bajas de los dispositivos
cercanos (sin líder, funciona sin conexión) y difunde sus carritos a las demás. Un carrito lo
comparten dos dispositivos que hablan con dos réplicas distintas, así que el mismo carrito se
edita en dos sitios a la vez.

Ahora mismo cada carrito es un valor con la hora del reloj de la réplica, y gana la marca más
nueva (gana la última escritura, como las celdas de Cassandra). Dos cambios del mismo carrito
hechos a la vez en dos réplicas no pueden ganar los dos: uno se pierde en silencio. Y cuando un
reloj salta (NTP), una escritura vieja con una marca equivocada le gana a todas las nuevas.

Haz las etapas en orden, en este archivo:

  Etapa 1  Relojes vectoriales: marca cada versión con un reloj vectorial ({réplica: cuenta})
           en vez de la hora. `compare` te dice si una versión ocurrió antes que otra o si son
           concurrentes; guarda cada versión concurrente como hermana (`keep_newest`) y fusiona
           las hermanas al leer. Ya no se pierde ningún alta, pero una baja puede revivir.
  Etapa 2  Un CRDT: haz de cada carrito un conjunto de bajas observadas (`ORSet`). Cada alta
           lleva una etiqueta única, una baja pone lápida a las etiquetas que esta réplica ha
           visto, y fusionar dos conjuntos es unirlos. Todas las réplicas acaban con el mismo
           carrito: nada perdido, nada que vuelva de entre los muertos.

Cómo habla tu nodo (mira core/net.py):
  self.node_id, self.node_ids      quién eres, y todas las réplicas ("n0" ... "n4")
  self.reply(msg, {...})           responde a una petición
  self.send(dest, {...})           envía sin esperar respuesta (se pierde si la red está partida)
  self.every(seconds, coroutine_function)    ejecuta algo cada cierto tiempo
  self.now()                       la hora de verdad (solo el comprobador puede usarla: las
                                   máquinas reales solo tienen self.clock(), que puede fallar)

La red le pasa al receptor los mismos objetos que pones en un mensaje: nunca cambies algo
después de enviarlo (envía copias, o valores que nunca cambias: tuplas, frozensets).

El comprobador llama a `items(cart)` en cada réplica (que sea rápido, y que sea el carrito que
devuelve una lectura). Cada dispositivo solo quita sus propios productos, y solo después de
haberlos añadido.

Compruébalo:  LABS_LANG=es uv run pytest labs/vector_clocks_crdts
Mira una solución (¡después de intentarlo!):  labs/vector_clocks_crdts/es/reference.py
"""

from __future__ import annotations

from core.net import Message, Node

GOSSIP = 1.0  # segundos entre dos rondas de anti-entropía (cada carrito, a cada par)


# ---------------------------------------------------------------- etapa 1: relojes vectoriales


def compare(a: dict, b: dict) -> str:
    """Cómo se relaciona el reloj de versión `a` con el reloj `b`. Un reloj es {id de réplica:
    cuenta}; una réplica que falta cuenta 0.

      "equal"       las mismas cuentas
      "before"      a ocurrió antes que b: cada cuenta de a es <= la de b, y no son iguales
      "after"       b ocurrió antes que a
      "concurrent"  ninguna: cada una ha visto algo que la otra no (un conflicto)

    compare({"n0": 1}, {"n0": 1, "n1": 2}) == "before"
    compare({"n0": 2}, {"n1": 1}) == "concurrent"
    """
    # Etapa 1: a_le = cada cuenta de a es <= la misma cuenta en b (b.get(node, 0)); b_le lo
    #          mismo al revés. Las dos: equal; solo a_le: before; solo b_le: after; ninguna:
    #          concurrent.
    raise NotImplementedError("PENDIENTE etapa 1: compare")


def keep_newest(versions: list) -> list:
    """Las hermanas: de las versiones (clock, items), descarta cada una de la que desciende otra
    (es "before" de otra, o "equal" a una ya guardada). Lo que queda son las versiones que nadie
    ha superado: una si no hubo conflicto, varias si lo hubo.

    keep_newest([({"n0": 1}, A), ({"n0": 2}, B)]) == [({"n0": 2}, B)]
    keep_newest([({"n0": 1}, A), ({"n1": 1}, B)]) == las dos, como hermanas
    """
    # Etapa 1: construye una lista `out`; para cada versión, sáltala si algún reloj guardado es
    #          "after" o "equal" a ella (compare(clock, kept) in ("before", "equal")); si no,
    #          quita las guardadas que son "before" de ella y guárdala.
    raise NotImplementedError("PENDIENTE etapa 1: keep_newest")


# ---------------------------------------------------------------- etapa 2: un CRDT


class ORSet:
    """Etapa 2. Un conjunto de bajas observadas: el carrito como CRDT.

      add(item, tag)    tag: única en todo el sistema, p. ej. f"{node_id}:{n}" con n creciendo
      remove(item)      pon lápida a cada etiqueta de `item` que esta réplica ha visto (un alta
                        que aún no ha visto no se quita: gana)
      items() -> set    los productos con al menos una etiqueta que no es lápida
      merge(other)      unión de etiquetas y unión de lápidas: el orden y las repeticiones no
                        importan (conmutativa, asociativa, idempotente)
      copy() -> ORSet   una copia para poner en un mensaje

    Pista: guarda `self.tags = {item: conjunto de etiquetas vivas}` y `self.removed = conjunto
    de lápidas`; así items() es rápido: los productos cuyo conjunto de etiquetas no está vacío.
    """

    def __init__(self) -> None:
        self.tags: dict[str, set] = {}
        self.removed: set = set()

    def add(self, item: str, tag: str) -> None:
        raise NotImplementedError("PENDIENTE etapa 2: ORSet.add")

    def remove(self, item: str) -> None:
        raise NotImplementedError("PENDIENTE etapa 2: ORSet.remove")

    def items(self) -> set[str]:
        raise NotImplementedError("PENDIENTE etapa 2: ORSet.items")

    def merge(self, other: "ORSet") -> None:
        # Toma primero las lápidas nuevas y quítalas de tus etiquetas vivas; luego añade sus
        # etiquetas vivas, menos tus lápidas.
        raise NotImplementedError("PENDIENTE etapa 2: ORSet.merge")

    def copy(self) -> "ORSet":
        raise NotImplementedError("PENDIENTE etapa 2: ORSet.copy")


class CartNode(Node):
    """Una réplica: acepta las escrituras de los dispositivos cercanos y difunde a las demás.

    Contrato:
      - `add` {cart, item}     -> responde {"type": "add_ok"} (al momento: sin esperar a nadie)
      - `remove` {cart, item}  -> responde {"type": "remove_ok"}
      - `read` {cart}          -> responde {"type": "read_ok", "items": [...]}
      - `items(cart)` -> set   lo que devolvería una lectura (el comprobador la llama)
    Todas las réplicas acaban con los mismos carritos, con cada alta confirmada y sin las bajas.
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.skew = 0.0  # lo pone el escenario
        self.peers = [n for n in node_ids if n != node_id]
        # Etapa 0: cart -> ((hora del reloj, id del nodo), frozenset de productos): un valor, gana la marca más nueva.
        # Etapa 1: cart -> [(reloj vectorial, frozenset de productos), ...]: las hermanas.
        # Etapa 2: cart -> ORSet.
        self.carts: dict = {}
        self.every(GOSSIP, self.gossip)

    def clock(self) -> float:
        """El reloj de pared de esta máquina, como time.time(). (Dado: un ajuste de NTP lo hace mentir.)"""
        return self.now() + self.skew

    # ---- el carrito: cambia esto en cada etapa

    def items(self, cart: str) -> set[str]:
        # Etapa 1: la unión de los productos de las hermanas (fusionar al leer).
        # Etapa 2: self.carts[cart].items().
        entry = self.carts.get(cart)
        return set(entry[1]) if entry else set()

    def add(self, cart: str, item: str) -> None:
        # Etapa 2: un add del ORSet con una etiqueta nueva (cuenta tus altas: f"{self.node_id}:{n}").
        self.put(cart, self.items(cart) | {item})

    def remove(self, cart: str, item: str) -> None:
        # Etapa 2: el remove del ORSet.
        self.put(cart, self.items(cart) - {item})

    def put(self, cart: str, items: set[str]) -> None:
        """Una escritura local del carrito entero."""
        # Etapa 1: el reloj nuevo es el máximo de los relojes de las hermanas, por réplica, más 1
        #          para self.node_id; la escritura reemplaza a todas las hermanas que leyó:
        #          self.carts[cart] = [(clock, frozenset(items))]. Crea un dict nuevo para el
        #          reloj: nunca cambies uno que quizá enviaste.
        self.carts[cart] = ((self.clock(), self.node_id), frozenset(items))

    def state(self, cart: str):
        """Qué enviarle a un par sobre un carrito."""
        # Etapa 1: list(self.carts[cart]).  Etapa 2: una copia del ORSet.
        return self.carts[cart]

    def merge(self, cart: str, theirs) -> None:
        """Incorpora la versión de un par de un carrito a la nuestra."""
        # Etapa 1: self.carts[cart] = keep_newest(nuestras hermanas + las suyas).
        # Etapa 2: fusiona su ORSet en el nuestro (crea uno vacío si no tenemos).
        mine = self.carts.get(cart)
        if mine is None or tuple(theirs[0]) > tuple(mine[0]):
            self.carts[cart] = theirs  # gana la última escritura: la otra versión se pierde

    # ---- clientes y difusión (dado: igual en todas las etapas)

    async def on_add(self, msg: Message) -> None:
        self.add(msg.body["cart"], msg.body["item"])
        self.push(msg.body["cart"])
        self.reply(msg, {"type": "add_ok"})

    async def on_remove(self, msg: Message) -> None:
        self.remove(msg.body["cart"], msg.body["item"])
        self.push(msg.body["cart"])
        self.reply(msg, {"type": "remove_ok"})

    async def on_read(self, msg: Message) -> None:
        self.reply(msg, {"type": "read_ok", "items": sorted(self.items(msg.body["cart"]))})

    def push(self, cart: str) -> None:
        """Cuéntale un cambio a cada par al momento (se pierde si la red está partida)."""
        body = {"type": "sync", "carts": {cart: self.state(cart)}}
        for peer in self.peers:
            self.send(peer, body)

    async def gossip(self) -> None:
        """Anti-entropía: cada carrito a cada par, para que una réplica que se perdió envíos se ponga al día."""
        if not self.carts:
            return
        body = {"type": "sync", "carts": {cart: self.state(cart) for cart in self.carts}}
        for peer in self.peers:
            self.send(peer, body)

    async def on_sync(self, msg: Message) -> None:
        for cart, theirs in msg.body["carts"].items():
            self.merge(cart, theirs)

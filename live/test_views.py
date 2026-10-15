"""A made-up lab plugs into the lanes view with only World hooks and a tiny adapter."""

from live.canvas import GREEN, RED, Canvas
from live.views import adapter_for, render
from live.views.base import ADAPTERS, adapts
from live.views.lanes import LaneAdapter, LaneFrame, slot
from live.worlds.base import World


class ToyWorld(World):
    id = "toy"
    title = "Toy"
    view = "lanes"

    def __init__(self, params=None):
        super().__init__(params)
        self.start("main")


@adapts("toy", "lanes")
class ToyLanes(LaneAdapter):
    def frame(self, variant, t, users):
        return LaneFrame(users={slot(7, users): (RED, True)}, flights=[(0, 0.5, GREEN, True)],
                         closed=t > 5, state=("OVERLOADED", RED))


def test_a_new_lab_plugs_in_with_hooks_and_a_tiny_adapter():
    world = ToyWorld()
    cv = Canvas(70, 20)
    render(world, cv, "main", 10.0)
    text = "\n".join(cv.plain())
    assert "OVERLOADED" in text and "●" in text
    assert adapter_for(world) is adapter_for(world)  # one adapter per world
    del ADAPTERS[("toy", "lanes")]


def test_state_is_centred_under_the_server():
    world = ToyWorld()
    ADAPTERS[("toy", "lanes")] = ToyLanes
    for cols in (50, 61, 68):
        cv = Canvas(cols, 20)
        render(world, cv, "main", 1.0)
        rows = cv.plain()
        box = rows[-2].rstrip()  # the bottom of the server: the last run of dots
        right = len(box) - 1
        left = len(box.rsplit(" ", 1)[0]) + 1 if " " in box else 0
        start = rows[-1].index("OVERLOADED")
        assert abs((left + right + 1) - (2 * start + 10)) <= 1
    del ADAPTERS[("toy", "lanes")]


def test_slot_spreads_neighbours():
    n = 60
    spots = [slot(i, n) for i in range(10)]
    assert len(set(spots)) >= 9
    assert sum(abs(a - b) > 3 for a, b in zip(spots, spots[1:])) >= 7


def test_the_cluster_view_draws_nodes_messages_and_a_partition_cut():
    from live.canvas import BLUE, RED
    from live.views.cluster import ClusterAdapter, ClusterFrame

    class Net(World):
        id, title, view = "toynet", "Toy net", "cluster"

        def __init__(self):
            super().__init__()
            self.start("main")

    @adapts("toynet", "cluster")
    class NetPicture(ClusterAdapter):
        def frame(self, variant, t):
            return ClusterFrame(nodes=[BLUE] * 9, groups=[0, 0, 1] * 3, flights=[(0, 4, 0.5, BLUE)],
                                drops=[(1, 2, 0.1)], state=("PARTITIONED  6 | 3", RED))

    cv = Canvas(60, 20)
    render(Net(), cv, "main", 1.0)
    text = "\n".join(cv.plain())
    assert text.count("◉") == 9 and "PARTITIONED  6 | 3" in text
    assert any(cv.cell(r, c)[1] == RED and cv.cell(r, c)[0] not in " ◉" for r in range(20) for c in range(60))
    del ADAPTERS[("toynet", "cluster")]


def test_a_lab_can_have_several_views_and_opens_with_its_own():
    from live.canvas import BLUE
    from live.views import next_view, set_view, views_for
    from live.views.cluster import ClusterAdapter, ClusterFrame

    class Both(World):
        id, title = "toyboth", "Toy both"  # view defaults to lanes

        def __init__(self):
            super().__init__()
            self.start("main")

    @adapts("toyboth", "lanes")
    class BothLanes(LaneAdapter):
        def frame(self, variant, t, users):
            return LaneFrame(state=("LANES", BLUE))

    @adapts("toyboth", "cluster")
    class BothCluster(ClusterAdapter):
        def frame(self, variant, t):
            return ClusterFrame(nodes=[BLUE] * 4, state=("CLUSTER", BLUE))

    w = Both()
    assert views_for(w) == ["lanes", "cluster"] and w.view == "lanes"

    def drawn():
        cv = Canvas(60, 20)
        render(w, cv, "main", 1.0)
        return "\n".join(cv.plain())

    assert "LANES" in drawn()
    assert next_view(w) == "cluster" and "CLUSTER" in drawn()
    assert next_view(w) == "lanes"
    set_view(w, "cluster")
    assert "CLUSTER" in drawn()
    import pytest

    with pytest.raises(LookupError):
        set_view(w, "globe")
    del ADAPTERS[("toyboth", "lanes")], ADAPTERS[("toyboth", "cluster")]


def test_client_lanes_colours_answers_and_can_put_red_ones_first():
    from live.adapters.common import OUTCOMES, client_lanes
    from live.canvas import EXTRA2

    class Run:  # 100 answers in the last 0.1 s: one red, a few orange, the rest green
        max_dur = {"ops": 0.0}
        rows_ = [(9.9 + i / 1000, 9.9 + i / 1000, "red" if i == 50 else "orange" if i % 10 == 0 else "ok")
                 for i in range(100)]

        def active(self, table, t, end):
            return []

        def rows(self, table, a, b):
            return [r for r in self.rows_ if a <= r[0] < b]

    colour = {"red": RED, "orange": EXTRA2, "ok": GREEN}
    _, _, plain = client_lanes(Run(), 10.0, 60, "ops", 0, 1, colour=lambda o: colour[o[2]])
    _, _, first = client_lanes(Run(), 10.0, 60, "ops", 0, 1, colour=lambda o: colour[o[2]], rare_first=True)
    assert len(plain) == len(first) == OUTCOMES
    assert RED not in [c for c, _ in plain]  # one red among a hundred is easily missed ...
    assert first[0][0] == RED and EXTRA2 in [c for c, _ in first]  # ... unless red goes first
    _, _, old = client_lanes(Run(), 10.0, 60, "ops", 0, 1, bad=lambda o: o[2] != "ok")
    assert {c for c, _ in old} <= {RED, GREEN}


def test_the_relay_variation_draws_two_servers_and_two_lines():
    from live.canvas import WHITE
    from live.views.lanes_relay import Relay, RelayFrame, draw_relay

    fr = RelayFrame(users={0: (WHITE, True)}, flights=[(0, 0.5, WHITE, False)], hops=[(0.5, WHITE, True)],
                    relay=Relay(label=("4 balancers", WHITE), fill=0.5), fill=0.8, state=("BUSY", WHITE))
    for cols in (50, 68):
        cv = Canvas(cols, 20)
        draw_relay(cv, lambda n: fr)
        lines = cv.plain()
        assert all(len(line) <= cols for line in lines)
        assert "4 balancers" in lines[-1] and "BUSY" in lines[-1]  # a word under each server
        assert lines[-1].index("4 balancers") < lines[-1].index("BUSY")  # the relay stands left of the server


def test_the_fanout_variation_draws_a_relay_and_its_small_servers():
    from live.canvas import RED, WHITE
    from live.views.lanes_fanout import FanoutFrame, Leaf, draw_fanout
    from live.views.lanes_relay import Relay

    fr = FanoutFrame(users={0: (WHITE, True)}, relay=Relay(label=("orchestrator", WHITE)),
                     leaves=[Leaf(("payments", WHITE), 0.5), Leaf(("stock", RED), 1.0, outline=RED),
                             Leaf(("shipping", WHITE))],
                     hops=[(0, 0.5, WHITE, False), (2, 0.3, WHITE, True)], state=("HALF DONE", RED))
    for cols, rows in ((50, 14), (68, 28)):
        cv = Canvas(cols, rows)
        draw_fanout(cv, lambda n: fr)
        lines = cv.plain()
        text = "\n".join(lines)
        assert all(len(line) <= cols for line in lines) and len(lines) == rows
        assert all(name in text for name in ("payments", "stock", "shipping", "orchestrator", "HALF DONE"))
        rows_of = [next(r for r, line in enumerate(lines) if name in line) for name in ("payments", "stock", "shipping")]
        assert rows_of == sorted(rows_of)  # stacked top to bottom, in order


def test_fanout_names_read_top_to_bottom_in_one_form_that_fits():
    from live.canvas import WHITE
    from live.views.lanes_fanout import FanoutFrame, Leaf, draw_fanout

    leaves = [Leaf(("payments", WHITE), short="pay", tiny="pay"), Leaf(("stock", WHITE), short="stock", tiny="stk"),
              Leaf(("shipping", WHITE), short="ship", tiny="shp")]
    fr = FanoutFrame(leaves=leaves, vertical=True)

    def names(rows: int) -> list[str]:
        cv = Canvas(68, rows)
        draw_fanout(cv, lambda n: fr)
        column = [line[-2] for line in cv.plain()[:-1]]  # the column right of the servers
        return "".join(ch if ch != " " else "|" for ch in column).split("|")

    assert [w for w in names(28) if w] == ["PAY", "STOCK", "SHIP"]  # room: the short forms (never the full names)
    # Little room: the tiny forms, all of them; names never on consecutive rows (they would read as one word).
    assert [w for w in names(13) if w] == ["PAY", "STK", "SHP"]


def test_a_new_picture_is_just_a_list_of_parts():
    from live.canvas import RED, WHITE
    from live.views.parts import Caption, Door, Server, Stage, UsersGrid, Wire, draw_parts

    cv = Canvas(60, 20)
    st = Stage.on(cv)
    draw_parts(st, [UsersGrid({0: (WHITE, True)}), Wire(st.gx + 2, 60), Door(62, closed=True),
                    Server(st.server_x, fill=0.5), Caption("DOWN", RED, st.server_x)])
    lines = cv.plain()
    assert lines[0].startswith(" ●") and "DOWN" in lines[-1] and all(len(line) <= 60 for line in lines)


def _peers_frame(n: int, groups=None, names=None):
    from live.canvas import BLUE, GREEN, WHITE
    from live.views.lanes_peers import LINE, Leaf, PeersFrame

    names = names or [(f"n{i} leader t4" if i == 0 else f"n{i} t4", f"n{i} t4", f"n{i}") for i in range(n)]
    peers = [Leaf((full, GREEN if i == 0 else BLUE), 0.5, short=short, tiny=tiny, outline=GREEN if i == 0 else BLUE)
             for i, (full, short, tiny) in enumerate(names)]
    return PeersFrame(users={0: (WHITE, True)}, requests=[(0, 0.5, WHITE, False)], peers=peers,
                      links=[(0, j, BLUE) for j in range(1, n)] + [(1, 2, LINE)], groups=groups,
                      flights=[(-1, 0, 0.5, WHITE)], state=("CONNECTED", GREEN))


def _draw_peers(fr, cols: int, rows: int):
    from live.views.lanes_peers import door_x, draw_peers
    from live.views.parts import PeerRing, Stage

    cv = Canvas(cols, rows)
    draw_peers(cv, lambda n: fr)
    st = Stage.on(Canvas(cols, rows))
    spots = PeerRing(fr.peers, int(door_x(st) // 2) + 3).place(st)
    return cv, spots


def test_the_peers_variation_puts_the_peers_on_a_ring_clockwise_from_the_top():
    from live.views.lanes_peers import door_x
    from live.views.parts import Stage

    for n in (3, 5, 8):
        for cols, rows in ((50, 12), (54, 14), (61, 20), (68, 28)):
            fr = _peers_frame(n)
            cv, spots = _draw_peers(fr, cols, rows)
            lines = cv.plain()
            assert len(lines) == rows and all(len(line) == cols for line in lines)
            assert "CONNECTED" in lines[-1]  # the state, under the ring
            top = min(s.y for s in spots)
            assert spots[0].y == top  # the first one at the top ...
            right = [s for s in spots[1:] if s.x > spots[0].x + 1]
            assert right and all(spots.index(s) <= (n + 1) // 2 for s in right)  # ... then clockwise
            for s in spots:  # every name whole, on the row under its peer, inside the picture
                assert s.name and lines[s.name_row][s.name_col:s.name_col + len(s.name)] == s.name
                assert s.name_row <= rows - 2 and s.name_col + len(s.name) <= cols
            door = int(door_x(Stage.on(cv)) // 2)
            assert all(s.col > door and s.name_col > door for s in spots)  # right of the door


def test_the_peers_variation_shrinks_names_then_boxes_when_cramped():
    from live.views.parts import ring_spots

    def cells(spots):
        out = []
        for s in spots:
            wc = 1 if s.box is None else (s.box[1] - s.box[0] + 1) // 2
            box = {(r, c) for r in range(s.row, s.name_row) for c in range(s.col, s.col + wc)}
            out.append(box | {(s.name_row, c) for c in range(s.name_col, s.name_col + len(s.name))})
        return out

    long = [(f"n{i} declared dead", f"n{i} dead", f"n{i}") for i in range(8)]
    roomy = ring_spots(68, 27, 8, 17, long)
    tight = ring_spots(50, 11, 8, 17, long)
    assert all(s.box is not None for s in roomy) and all(s.box is not None for s in tight)
    assert len(tight[0].name) < len(roomy[0].name)  # a shorter name when cramped, the same form for all
    assert len({len(s.name) - len(str(i)) for i, s in enumerate(tight)}) == 1
    crowd = ring_spots(50, 11, 10, 17, [(f"n{i}",) for i in range(10)])
    assert all(s.box is None for s in crowd)  # no room for boxes: a ◉ each
    for spots in (roomy, tight, crowd):
        taken = cells(spots)
        assert all(not (taken[i] & taken[j]) for i in range(len(spots)) for j in range(i + 1, len(spots)))


def test_the_peers_variation_cuts_the_links_between_groups_and_shows_what_flies():
    from live.canvas import RED, WHITE

    fr = _peers_frame(5, groups=[0, 0, 1, 1, 1])
    fr.drops = [(0, 3, 0.0)]
    cv, spots = _draw_peers(fr, 68, 28)
    cuts = [(r, c) for r in range(28) for c in range(68) if cv.cell(r, c) == ("✕", RED)]
    assert len(cuts) == 4  # 0-2, 0-3, 0-4 and 1-2 cross the cut; 0-1 does not
    reds = [(r, c) for r in range(28) for c in range(68) if cv.cell(r, c)[1] == RED and cv.cell(r, c)[0] != "✕"]
    assert reds  # the lost message, short of the middle of 0-3
    plain, _ = _draw_peers(_peers_frame(5), 68, 28)
    assert "✕" not in "\n".join(plain.plain())  # no partition, no cut
    door_flight = [(r, c) for r in range(26) for c in range(16, 68) if cv.cell(r, c)[1] == WHITE
                   and cv.cell(r, c)[0] not in " ○●"]
    assert door_flight  # a request on its way from the door to n0
    r, c = door_flight[0]
    assert c < spots[0].col and r < 14  # between the door (left, middle) and n0 (top)

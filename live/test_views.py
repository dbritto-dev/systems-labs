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


def test_the_pipeline_variation_draws_a_row_of_boxes_with_their_names_under_them():
    from live.canvas import BG, BLUE, GREEN, RED, WHITE, mix
    from live.views.lanes_pipeline import Leaf, PipelineFrame, draw_pipeline
    from live.views.parts import Stage

    names = [("service", "svc", "S"), ("db", "db", "db"), ("relay", "relay", "R"), ("broker", "brkr", "B"),
             ("shipping", "ship", "sh")]
    fr = PipelineFrame(users={0: (WHITE, True)}, flights=[(0, 0.5, WHITE, False)], outcomes=[(GREEN, 0.1)],
                       boxes=[Leaf((n, WHITE), 0.5, short=s, tiny=t) for n, s, t in names],
                       hops=[(1, 0.5, BLUE, False), (4, 0.5, GREEN, True)], drops=[(2, 0.1)],
                       state=("RESTARTING", RED))
    for cols, rows in ((50, 12), (54, 14), (68, 28)):  # the smallest picture, 92x30, 110x44 (and 200x70)
        cv = Canvas(cols, rows)
        draw_pipeline(cv, lambda n: fr)
        lines = cv.plain()
        assert len(lines) == rows and all(len(line) <= cols for line in lines)
        assert "RESTARTING" in lines[-1] and lines[-1].index("RESTARTING") < 12  # the state, under the users
        under = lines[-2] + " " + lines[-1]
        words = [next((w for w in forms if f" {w} " in f" {under} "), None) for forms in names]
        assert None not in words, (cols, under)  # every box has a whole name, in one of its forms
        if cols == 68:
            assert words == [n for n, _, _ in names]  # with room, the full names
        assert not lines[0][cols // 2:].strip()  # the band over the boxes is empty: nothing skips
        mid = int(Stage.on(cv).ymid // 4)  # the middle row: the line the requests travel along
        assert any(cv.cell(mid, c)[1] == GREEN for c in range(cols))  # a hop between the boxes
        assert any(cv.cell(mid, c)[1] == mix(RED, BG, 0.1) for c in range(cols))  # a drop, fading red


def test_pipeline_boxes_sit_left_to_right_and_the_out_ones_after_a_gap():
    from live.canvas import MUTED, WHITE
    from live.views.lanes_pipeline import Leaf, PipelineFrame, draw_pipeline
    from live.views.parts import Boxes

    leaves = [Leaf((f"n{i}", WHITE)) for i in range(4)]
    inline = Boxes(leaves, 50.0, 134.0)
    gapped = Boxes(leaves, 50.0, 134.0, gap_after=2)
    assert inline.xs == sorted(inline.xs) and gapped.xs == sorted(gapped.xs)
    steps = [b - a for a, b in zip(gapped.xs, gapped.xs[1:])]
    assert steps[2] > steps[1] + 4  # a gap before the box out of the line
    assert 2 * gapped.rx <= 16 and gapped.xs[-1] + gapped.rx <= 134

    fr = PipelineFrame(boxes=leaves, gap_after=2, skips=[(-1, 2, 0.5, MUTED)], state=("OK", WHITE))
    cv = Canvas(68, 28)
    draw_pipeline(cv, lambda n: fr)
    lines = cv.plain()
    assert (lines[0] + lines[1])[34:68].strip() or lines[1][34:].strip()  # the arc over the top
    top = next(r for r, line in enumerate(lines) if "⡤" in line or "⢠" in line)
    assert top >= 2  # the boxes start under the arcs' band
    door = int((22 + (136 - 22) * 0.28) // 2)
    assert all(lines[top][c] == " " for c in range(door + 1, door + 3))  # the first box is clear of the door
    drawn = Boxes(leaves, 22 + (136 - 22) * 0.28, 134.0, gap_after=2)  # where draw_pipeline puts them
    case = [cv.cell(top + 2, int((x - drawn.rx) // 2))[1] for x in drawn.xs]  # each box's left side
    assert case[0] == case[1] == case[2] != case[3]  # the box out of the line is dimmed

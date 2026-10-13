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

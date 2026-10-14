import itertools

import pytest

from core.testing import build_world
from labs.retry_storm import scenario
from live.runner import Feed
from live.worlds import make_world
from live.worlds.base import KEEP


@pytest.fixture(scope="module")
def world():
    return build_world("retry_storm", "reference", 8)


def test_pieces_join_in_order(world):
    run = world.runs["reference"]
    keys = run.keys["requests"]
    assert keys == sorted(keys)
    ids = [r[0] for r in run.tables["requests"]]
    assert len(set(ids)) == len(ids)
    assert [i.t0 for i in run.incidents] == sorted(i.t0 for i in run.incidents)
    assert run.end == 480.0


def test_old_raw_rows_are_forgotten_but_totals_stay(world):
    run = world.runs["reference"]
    assert run.keys["requests"][0] > 60  # minute 0 is gone
    assert run.earliest == run.end - KEEP
    pieces = list(itertools.islice(scenario.stream("reference"), 8))
    served = sum(r[3] for p in pieces for r in p["tables"]["requests"])
    failed = sum(not r[3] for p in pieces for r in p["tables"]["requests"])
    stats = dict((k, v) for k, v, _ in world.user_stats("reference", 500.0))
    assert int(stats["served"].replace(",", "")) == served
    assert int(stats["failed"].replace(",", "")) == failed


def test_one_run_never_restarts(world):
    run = world.runs["reference"]
    # Incidents come at random and can cross minute boundaries.
    gaps = [b.t0 - a.t1 for a, b in zip(run.incidents, run.incidents[1:])]
    assert min(gaps) >= scenario.QUIET and len(set(round(g) for g in gaps)) > 2
    assert any(int(i.t0 // 60) != int(i.t1 // 60) for i in run.incidents)
    # Request ids just keep counting: no minute starts over.
    ids = [r[0] for r in run.tables["requests"]]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_first_incident_is_always_the_same():
    first = [next(scenario.incidents(seed)) for seed in (1, 2, 99)]
    assert all((i.t0, i.t1, i.kind) == (20.0, 30.0, "outage") for i in first)
    a = list(itertools.islice(scenario.incidents(5), 30))
    assert a == list(itertools.islice(scenario.incidents(5), 30))
    assert a != list(itertools.islice(scenario.incidents(6), 30))
    assert {i.kind for i in a} == {"outage", "errors"}
    assert all(i.cause for i in a)


def test_goals_never_spoil_the_future():
    from labs.retry_storm.test_lab import NAIVE

    w = build_world("retry_storm", NAIVE, 2)
    # Before the outage ends, the 'during' goals are still waiting, unless they can no longer pass:
    # 50 ms retries put ~4x the load on, so the load goal alerts early.
    rows = w.goal_lines(NAIVE, 25.0)
    assert [r.status for r in rows] == ["ok", "wait", "wait", "wait", "alert", "wait"]
    rows = w.goal_lines(NAIVE, 30.5)
    assert [r.status for r in rows] == ["ok", "ok", "alert", "alert", "alert", "wait"]
    assert "ends" in w.next_check(NAIVE, 25.0)


def test_feed_streams_one_endless_run():
    world = make_world("retry_storm")
    feed = Feed(world, "retry_storm", "reference")
    feed.restart()
    first = feed.job
    feed.restart()  # replaces generation 1 before it arrives
    assert first.dead and first is not feed.job
    assert feed.loading[0] == "starting"
    feed.build_until(100.0)
    run = world.runs["reference"]
    assert run.gen == feed.gen == 3 and run.end >= 140.0
    assert feed.loading is None  # the first minute is in
    feed.tick(run.end - 10)  # close to the end: the next minute is asked for
    assert feed.busy
    feed.close()


def test_build_until_and_errors_reach_the_screen(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("class Client:\n    pass\nbackoff_delay = RetryBudget = None\n")
    world = make_world("retry_storm")
    feed = Feed(world, "retry_storm", str(bad))
    feed.build_until(10)
    assert "TypeError" in feed.error and "bad.py" in feed.error


def test_the_child_says_your_code_loaded_before_the_first_minute():
    import time

    from live.runner import StreamJob

    job = StreamJob("labs.caching.scenario:stream", "reference", {"seed": 1})
    job.request()
    seen = []
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if job.progress not in seen:
            seen.append(job.progress)
        if (r := job.poll()) is not None:
            assert r[0] == "ok"
            break
        time.sleep(0.01)
    job.cancel()
    assert seen[:2] == ["starting", "loaded"]

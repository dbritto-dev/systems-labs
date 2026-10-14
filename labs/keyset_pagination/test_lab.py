import itertools

import pytest

from core.contract import load
from core.testing import build_world, variant, your_code
from core.vtime import run_virtual
from labs.keyset_pagination import reference, scenario
from labs.keyset_pagination.api import PAGE_SIZE, BadCursor, Database, Page, Post, current_page

code = load("keyset_pagination", variant(), scenario.NAMES)
SEEDS = (1, 2, 3)
SKIPPED, DUP, DEEP, ROWS = 1, 2, 3, 4  # goal positions after the baseline


class CREATED_AT:  # stage 1: WHERE created_at < the last post's created_at
    encode_cursor = staticmethod(reference.encode_cursor)
    decode_cursor = staticmethod(reference.decode_cursor)

    class FeedAPI(reference.FeedAPI):
        async def list_posts(self, cursor):
            if cursor is None:
                rows = await self.db.select(PAGE_SIZE)
            else:
                rows = await self.db.select(PAGE_SIZE, older_than=int(cursor))
            return Page(rows, str(rows[-1].created_at) if len(rows) == PAGE_SIZE else None)


class AT_OR_OLDER:  # WHERE created_at <= ...: nothing skipped, but a tie that does not fit comes back
    encode_cursor = staticmethod(reference.encode_cursor)
    decode_cursor = staticmethod(reference.decode_cursor)

    class FeedAPI(reference.FeedAPI):
        async def list_posts(self, cursor):
            if cursor is None:
                rows = await self.db.select(PAGE_SIZE)
            else:
                rows = await self.db.select(PAGE_SIZE, older_than=int(cursor) + 1)
            return Page(rows, str(rows[-1].created_at) if len(rows) == PAGE_SIZE else None)


class OFFSET_IN_A_CURSOR:  # an opaque cursor, but it still holds an offset: as slow and as wrong as OFFSET
    encode_cursor = staticmethod(reference.encode_cursor)
    decode_cursor = staticmethod(reference.decode_cursor)

    class FeedAPI(reference.FeedAPI):
        async def list_posts(self, cursor):
            offset = reference.decode_cursor(cursor)[1] if cursor else 0
            rows = await self.db.select(PAGE_SIZE, offset=offset)
            more = len(rows) == PAGE_SIZE
            return Page(rows, reference.encode_cursor(Post(offset + PAGE_SIZE, 0)) if more else None)


class BY_ID:  # the cursor is the last post's id, looked up again: a deleted post breaks the walk
    encode_cursor = staticmethod(reference.encode_cursor)
    decode_cursor = staticmethod(reference.decode_cursor)

    class FeedAPI(reference.FeedAPI):
        async def list_posts(self, cursor):
            if cursor is None:
                rows = await self.db.select(PAGE_SIZE)
            else:
                post = await self.db.get(int(cursor))
                if post is None:
                    raise BadCursor(cursor)
                rows = await self.db.select(PAGE_SIZE, older_than=(post.created_at, post.id))
            return Page(rows, str(rows[-1].id) if len(rows) == PAGE_SIZE else None)


def first(v, seed=1):
    world = build_world("keyset_pagination", v, 1, seed=seed)
    return world, [r.ok for r in world.runs[v].settled[0]]


def statuses(world, v):
    run = world.runs[v]
    return [[r.ok for r in run.settled[i]] for i in sorted(run.settled)
            if all(r is not None for r in run.settled[i])]


# ------------------------------------------------------------- given behaviour


@pytest.mark.parametrize("seed", SEEDS)
def test_offset_repeats_posts_and_reads_thousands_of_rows(seed):
    world, ok = first("main", seed)
    assert ok[0] and not ok[DUP] and not ok[DEEP] and not ok[ROWS]
    assert world.stage_index("main") == 0  # OFFSET


@pytest.mark.parametrize("seed", SEEDS)
def test_keyset_on_created_at_is_cheap_but_skips_a_bulk_import(seed):
    world, ok = first(CREATED_AT, seed)
    assert ok[DUP] and ok[DEEP] and ok[ROWS] and not ok[SKIPPED]
    assert world.stage_index(CREATED_AT) == 1  # Keyset on created_at


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_at_or_older_shows_a_bulk_import_again(seed):
    world, ok = first(AT_OR_OLDER, seed)
    assert ok[SKIPPED] and not ok[DUP] and ok[ROWS]
    assert world.stage_index(AT_OR_OLDER) == 1


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_an_opaque_cursor_holding_an_offset_is_still_offset(seed):
    world, ok = first(OFFSET_IN_A_CURSOR, seed)
    assert not ok[DUP] and not ok[ROWS]
    assert world.stage_index(OFFSET_IN_A_CURSOR) == 0


def test_a_cursor_that_points_at_a_post_breaks_when_spam_is_purged():
    world = build_world("keyset_pagination", BY_ID, 2, seed=4)  # 0:58-1:10 purges 261 posts a second
    run = world.runs[BY_ID]
    purge = next(i for i in run.incidents if i.kind == "cleanup")
    assert not statuses(world, BY_ID)[purge.index][DUP]  # its cursor post is gone: 400, start over, repeats
    from live.worlds.keyset_pagination import P_OUTCOME

    assert any(p[P_OUTCOME] == scenario.BAD for p in run.rows("pages", purge.t0, purge.t1))


def test_reference_passes_every_goal_on_every_kind_of_incident():
    world = build_world("keyset_pagination", "reference", 6, seed=5)
    run = world.runs["reference"]
    results = statuses(world, "reference")
    assert len(results) >= 5 and {i.kind for i in run.incidents} >= {"import", "sync", "cleanup"}
    assert all(all(r) for r in results), results
    assert world.stage_index("reference") == 2  # Keyset (created_at, id)


def test_pieces_join_in_order_and_totals_survive_forgetting():
    world = build_world("keyset_pagination", "reference", 7, params={"rate": 4.0})  # quieter: quicker
    run = world.runs["reference"]
    assert run.keys["pages"] == sorted(run.keys["pages"])
    assert run.keys["pages"][0] >= 60  # the first minute's raw rows are gone
    pieces = itertools.islice(scenario.stream("reference", rate=4.0), 7)
    asked = sum(len(p["tables"]["pages"]) for p in pieces)
    assert run.total("asks", 1e9) == asked


def _posts(*created):
    return [Post(i + 1, c) for i, c in enumerate(created)]


def test_the_database_reads_what_offset_skips_and_seeks_with_a_key():
    async def main():
        db = Database(_posts(*range(1000, 1100)))
        page = {"id": 0, "read": 0, "queries": 0}
        current_page.set(page)
        deep = await db.select(20, offset=60)
        after_deep = page["read"]
        seek = await db.select(20, older_than=(deep[-1].created_at, deep[-1].id))
        return deep, after_deep, seek, page["read"] - after_deep

    deep, read_offset, seek, read_seek = run_virtual(main())
    assert [p.created_at for p in deep] == list(range(1039, 1019, -1)) and read_offset == 80
    assert [p.created_at for p in seek] == list(range(1019, 999, -1)) and read_seek == 20


# ------------------------------------------------------------- your code


async def _walk(api, db, change=None) -> list[int]:
    """Page to the end; `change(db, n)` runs between page n and n + 1."""
    ids, cursor, n = [], None, 0
    while True:
        page = await api.list_posts(cursor)
        ids += [p.id for p in page.items]
        cursor = page.next_cursor
        if cursor is None or n > 100:
            return ids
        if change is not None:
            change(db, n)
        n += 1


@your_code(1, "a keyset walk reads ~one page of rows per page, however deep")
def test_stage1_deep_pages_read_one_page():
    async def main():
        db = Database(_posts(*range(10_000, 12_000)))
        api = code.FeedAPI(db)
        page = {"id": 0, "read": 0, "queries": 0}
        current_page.set(page)
        ids = await _walk(api, db)
        return ids, page["read"]

    ids, read = run_virtual(main())
    assert sorted(ids) == list(range(1, 2001))
    assert read <= 2 * len(ids) + 2 * PAGE_SIZE  # OFFSET would read ~100,000


def _insert(db, n):
    """Five new posts at the top between two pages."""
    for k in range(5):
        db.insert(Post(10_000 + 5 * n + k, 50_000 + 5 * n + k))


@your_code(1, "posts written at the top while you page are not shown twice")
def test_stage1_inserts_at_the_top_do_not_repeat():
    async def main():
        db = Database(_posts(*range(1000, 1200)))
        return await _walk(code.FeedAPI(db), db, _insert)

    ids = run_virtual(main())
    assert len(ids) == len(set(ids)) and set(range(1, 201)) <= set(ids)


@your_code(1, "the first bulk import: rows read and deep pages OK")
def test_stage1_first_incident_cheap():
    world, ok = first(variant())
    assert ok[DEEP] and ok[ROWS]


@your_code(2, "decode_cursor(encode_cursor(post)) gives (created_at, id) back")
def test_stage2_cursor_round_trip():
    for post in (Post(1, 0), Post(42, 1_760_000_000_123), Post(2 ** 40, 2 ** 45)):
        cursor = code.encode_cursor(post)
        assert isinstance(cursor, str) and str(post.id) not in cursor  # opaque, not "t,id"
        assert tuple(code.decode_cursor(cursor)) == (post.created_at, post.id)


@your_code(2, "a cursor that is not yours is a BadCursor (400), not a crash")
def test_stage2_bad_cursors_are_rejected():
    import base64

    for bad in ("", "40", "not base64!", base64.urlsafe_b64encode(b"[1, 2]").decode(),
                base64.urlsafe_b64encode(b'{"t": "x", "id": 1}').decode(),
                base64.urlsafe_b64encode(b'{"t": 1}').decode()):
        with pytest.raises(BadCursor):
            code.decode_cursor(bad)


@your_code(2, "300 posts with one created_at, new posts on top: every old one exactly once")
def test_stage2_ties_are_neither_skipped_nor_repeated():
    async def main():
        db = Database(_posts(*([5000] * 300 + list(range(5001, 5100)))))
        return await _walk(code.FeedAPI(db), db, _insert)

    ids = run_virtual(main())
    assert sorted(i for i in ids if i < 10_000) == list(range(1, 400))


@your_code(2, "the cursor still works when the post it came from is deleted")
def test_stage2_cursor_survives_its_post_being_deleted():
    def purge(db, n):
        for pid in (381 - 20 * n, 382 - 20 * n):  # the last two posts shown: the cursor's own post too
            db.delete(pid)

    async def main():
        db = Database(_posts(*range(1000, 1400)))
        return await _walk(code.FeedAPI(db), db, purge)

    assert sorted(run_virtual(main())) == list(range(1, 401))


@your_code(2, "the first bulk import: every goal OK")
def test_stage2_first_incident_every_goal():
    world, ok = first(variant())
    assert ok == [True] * 5
    assert world.stage_index(variant()) == 2


def test_two_pictures_lanes_first():
    from live.canvas import EXTRA3, PURPLE, RED, plain
    from live.frame import compose
    from live.views import adapter_for, set_view, views_for

    def picture(v):
        world = build_world("keyset_pagination", v, 1)
        assert views_for(world) == ["lanes", "cluster"] and world.view == "lanes"  # lanes opens first
        lanes = [adapter_for(world).frame(v, 25.0 + k / 4, 60) for k in range(20)]  # in the import
        set_view(world, "cluster")
        frames = [adapter_for(world).frame(v, 25.0 + k / 4) for k in range(20)]
        assert all(len(f.nodes) == scenario.APIS + 4 for f in frames)
        text = "\n".join(plain(line) for line in compose(world, v, 25.0, 92, 30))
        assert frames[0].state[0] in text  # the line under the grid fits the smallest screen
        return lanes, frames

    given_lanes, given = picture("main")
    assert PURPLE in [c for f in given_lanes for c, _ in f.outcomes]  # repeated posts at the door
    assert EXTRA3 in [c for f in given_lanes for _, _, c, _ in f.flights]  # deep OFFSET scans
    assert EXTRA3 in [c for f in given for c in f.nodes]  # a worker busy with one
    stage1_lanes, stage1 = picture(CREATED_AT)
    assert RED in [c for f in stage1_lanes for c, _ in f.outcomes]  # skipped posts at the door
    assert EXTRA3 not in [c for f in stage1 for c in f.nodes]

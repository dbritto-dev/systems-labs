"""Lab keyset_pagination, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "Keyset pagination"
SUMMARY = "Clients page through a feed while posts come and go. Show each post once, fast at any depth."
PARAMS = {"rate": "readers per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"import": "IMPORT", "viral": "VIRAL", "cleanup": "PURGE", "sync": "SYNC", "calm": "CALM"}
CAUSES = {
    "txn_now": "a bulk insert in one transaction: now() is the same for every row",
    "csv_import": "an admin imports a CSV, every row stamped with the upload time",
    "migration": "posts migrated from the old app, all stamped with the migration time",
    "seed_job": "a job seeds a new community with welcome posts",
    "breaking_news": "breaking news: everyone posts at once",
    "match_final": "the last minutes of a cup final",
    "trending": "a hashtag starts trending",
    "celebrity": "a celebrity joins and their fans pour in",
    "spam_wave": "moderation removes last night's spam wave",
    "bot_ban": "a bot network is banned and its posts deleted",
    "erasure": "account erasure requests are processed in bulk",
    "takedown": "a legal takedown removes a batch of posts",
    "reindex": "the search cluster is rebuilt from scratch",
    "partner_export": "a partner exports the whole feed through the API",
    "warehouse": "the data warehouse backfills from the API",
    "app_release": "a new app version syncs the feed for offline reading",
}

STAGES = [
    StageText("OFFSET",
              "Challenge: rows shift between pages, so posts repeat or vanish; deep pages read it all.",
              "Stage 1: a keyset cursor: WHERE created_at < last seen"),
    StageText("Keyset on created_at",
              "Challenge: fast at any depth, but posts that share a created_at are skipped. Break ties.",
              "Stage 2: an opaque (created_at, id) cursor"),
    StageText("Keyset (created_at, id)",
              "Solved: every post exactly once, ~20 rows read per page at any depth.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "list_posts() must answer"),
    "skipped": GoalText("Skipped = 0", "break ties with the id"),
    "dup": GoalText("Repeated = 0", "a keyset cursor, not OFFSET"),
    "deep": GoalText("Deep p99 < 25ms", "seek, do not OFFSET"),
    "rows": GoalText("Rows/page ≤ 40", "WHERE ... < cursor"),
}

LEGEND = {"idle": "idle", "cheap": "page ~20 rows", "scans": "rows read 10x,100x,1000x",
          "skipped": "posts skipped", "repeated": "posts repeated", "served": "served",
          "limit": "4 workers", "incident": "incident"}

STRINGS = {
    # incidents
    "title_import": "Import",
    "title_viral": "Viral",
    "title_cleanup": "Purge",
    "title_sync": "Sync",
    "import_start": "{n:,.0f} posts written with one created_at: {cause}",
    "import_end": "the import has finished",
    "viral_start": "{n:.0f} posts/s at the top, twice the readers: {cause}",
    "viral_end": "posting is back to normal",
    "cleanup_start": "{n:.0f} recent posts deleted a second: {cause}",
    "cleanup_end": "the cleanup has finished",
    "sync_start": "{n:.0f} more jobs walk the whole feed: {cause}",
    "sync_end": "the sync jobs have stopped",
    "warn_skipped": "{n:,} posts skipped",
    "warn_dup": "{n:,} posts shown twice",
    # goal values
    "count": "{n:,}",
    # the panel
    "tile_skipped": "Skipped",
    "tile_dup": "Repeated",
    "tile_rows": "Rows/page",
    "stat_deep": "deep p99",
    "bar_readers": "Readers",
    "bar_sync": "Sync jobs",
    "bar_posts": "Posts",
    "title": "Pages",
    "head_skipped": "{n:,} posts skipped in 10 s",
    "head_dup": "{n:,} posts shown twice in 10 s",
    "head_deep": "Page {page:,} read {rows:,} rows",
    "head_import": "One created_at for hundreds of posts",
    "head_viral": "Posts pour in at the top",
    "head_cleanup": "Recent posts are being deleted",
    "head_sync": "Sync jobs walk the whole feed",
    "head_ok": "{rows:,} posts; each page reads ~20",
    "note_chart": "Chart: database busy time, % of 4 workers.",
    # the pictures
    "state_skipping": "SKIPPING",
    "state_repeating": "REPEATING",
    "state_scans": "DEEP SCANS",
    "state_import": "IMPORT",
    "state_viral": "VIRAL",
    "state_cleanup": "PURGE",
    "state_sync": "SYNC JOBS",
    "pic_state": "3 APIs → 4 workers · {rows} rows/page: {state}",
    # errors in your code
    "stuck": "a page has been running for over {seconds:.0f} s: does list_posts() ever return?",
}

LESSON = Lesson(
    title="Keyset pagination",
    one_liner="Page by where you are (the last key you showed), not by how many rows came before.",
    learn=(
        "LIMIT 20 OFFSET 40 means \"skip the first 40 rows, as they are now\". Between two requests the "
        "rows move: a post written at the top pushes everything down one place, so the next page "
        "repeats a post; a post deleted above you pulls everything up one, and a post is never shown. "
        "Nobody gets an error, just a wrong list.",
        "OFFSET is also slow where it hurts. The database cannot jump to row 20,000: it walks the "
        "index from the top and throws the first 20,000 rows away. A sync job paging through the "
        "whole table reads n^2/2 rows, and its deep pages hold workers that everyone else waits for.",
        "Keyset (seek) pagination remembers where the client is: the sort key of the last row it got. "
        "The next page is WHERE created_at < :last ORDER BY created_at DESC LIMIT 20. The index seeks "
        "straight there and reads 20 rows, on page 1 or page 10,000, and rows written or deleted "
        "elsewhere do not move it.",
        "The key must be unique. Many rows can share a created_at (a bulk insert in one transaction "
        "gets one now()); with < you skip the ones that did not fit on the page, with <= you show them "
        "again. Add a tiebreaker: ORDER BY created_at DESC, id DESC and WHERE (created_at, id) < "
        "(:t, :id), with an index on (created_at, id).",
        "Hand the key back as an opaque cursor (base64 of a little JSON), so clients do not build or "
        "edit it and you can change it later; reject what does not decode with a 400. Sign it (HMAC) "
        "if clients must not forge one. It holds values, not a pointer: it still works after its row "
        "is deleted. Do not look the row up again by id.",
    ),
    watch_for=(
        "OFFSET: repeated posts (purple) whenever posts are written above the readers, skipped ones "
        "(red) when posts are deleted, and the indexer's pages read thousands of rows (deep orange).",
        "Keyset on created_at: ~20 rows a page and no repeats, but at the bulk import every walk that "
        "reaches the import's created_at jumps past the posts that did not fit on its page (red).",
        "Keyset (created_at, id): nothing red or purple, ~20 rows read per page, deep pages as fast as page 1.",
    ),
    build=(
        ("SQL: the keyset query and its index",
         "CREATE INDEX posts_feed ON posts (created_at DESC, id DESC);\n"
         "SELECT id, created_at, body FROM posts\n"
         "WHERE (created_at, id) < ($1, $2)      -- the cursor\n"
         "ORDER BY created_at DESC, id DESC\n"
         "LIMIT 20;"),
        ("Python: an opaque cursor",
         "def encode(post):\n"
         "    data = json.dumps({\"t\": post.created_at, \"id\": post.id}).encode()\n"
         "    return base64.urlsafe_b64encode(data).decode()\n"
         "\n"
         "def decode(cursor):\n"
         "    try:\n"
         "        d = json.loads(base64.urlsafe_b64decode(cursor))\n"
         "        return int(d[\"t\"]), int(d[\"id\"])\n"
         "    except Exception:\n"
         "        raise BadCursor(cursor)   # -> 400"),
        ("HTTP: the next page as a link",
         "GET /posts?limit=20\n"
         "-> 200 {\"items\": [...], \"next_cursor\": \"eyJ0IjoxNzYw...\"}\n"
         "GET /posts?limit=20&cursor=eyJ0IjoxNzYw...\n"
         "-> 400 when the cursor does not decode"),
    ),
    checklist=(
        "The sort order is total: it ends with a unique column (the id).",
        "There is an index on exactly the sort columns, in that order.",
        "The cursor holds the last row's sort values, not an offset and not just its id.",
        "The comparison is strict and covers every sort column: (created_at, id) < (t, id).",
        "Cursors are opaque to clients; a bad one is a 400, never a 500 or another page.",
        "Deep pages cost the same as page 1: check rows read per page, not just latency.",
        "Jumping to page 37 is not possible with a cursor; offer filters or dates instead.",
    ),
    refs=(
        Ref("Markus Winand: We need tool support for keyset pagination",
            "https://use-the-index-luke.com/no-offset",
            "Why OFFSET is slow and unstable, and the seek method with row values."),
        Ref("Use The Index, Luke: Paging through results",
            "https://use-the-index-luke.com/sql/partial-results/fetch-next-page",
            "The seek method step by step, and why the order must be deterministic."),
        Ref("PostgreSQL: LIMIT and OFFSET",
            "https://www.postgresql.org/docs/current/queries-limit.html",
            "\"The rows skipped by an OFFSET clause still have to be computed inside the server.\""),
        Ref("PostgreSQL: Row constructor comparison",
            "https://www.postgresql.org/docs/current/functions-comparisons.html",
            "(a, b) < (c, d): how a row comparison works, column by column."),
        Ref("Slack Engineering: Evolving API pagination at Slack",
            "https://slack.engineering/evolving-api-pagination-at-slack/",
            "Why Slack moved its API from offsets to opaque cursors."),
        Ref("Stripe API: Pagination",
            "https://docs.stripe.com/api/pagination",
            "Cursor-based pagination with starting_after: the id of the last object you got."),
    ),
    try_next=(
        "Do stage 1 in labs/keyset_pagination/main.py and watch the deep orange scans and purple repeats go.",
        "Then watch the first bulk import: why are posts still skipped?",
        "Do stage 2, then run --seed 4 and watch a purge: the cursor's own post is deleted, and nothing breaks.",
    ),
)

# Lab: keyset pagination

*[Leer en español](es/README.md)*

An API lists a feed of ~40,000 posts, newest first, 20 to a page, through three API servers,
each with its own `FeedAPI.list_posts(cursor)` over one database (4 workers, 10 µs per row read).
~10 people a second open the feed and scroll 1–8 pages; a search indexer walks the whole feed,
page after page, and starts over when it reaches the end. Meanwhile ~4 posts a second are written
at the top and ~0.5 a second deleted. Every page is checked against the truth: a post that existed
when the client started walking, and still exists, must come exactly once. At random times, like
in production, a bulk import writes hundreds of posts with one `created_at` (one transaction, one
`now()`; a CSV upload; a migration), a viral moment pours 40–120 posts a second in at the top,
a spam purge deletes 100–300 recent posts a second, or sync jobs (a reindex, a partner export)
walk the whole feed at full speed. The run never restarts. The first incident is always a bulk
import at 0:20–0:30.

```
uv run python -m live keyset_pagination          # watch it; edit main.py and save
uv run python -m live keyset_pagination --lesson # the concept, links and a checklist
uv run pytest labs/keyset_pagination             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 OFFSET (given) | `select(20, offset=n)`, the cursor is the offset | ~1,000 posts repeated in the first import (purple: posts written above the readers shift every row down), thousands skipped in a purge (red), ~1,500–1,900 rows read per page and a deep p99 of 70–280 ms (the indexer's pages read everything above them) |
| 1 Keyset on `created_at` | `select(20, older_than=last.created_at)`, the cursor is that number | 20 rows a page, deep p99 ~3 ms, nothing repeated; but every walk that reaches the import's one `created_at` jumps past the posts that did not fit on its page: ~5,000–8,600 skipped (red), and again whenever the indexer passes an old import |
| 2 Keyset on `(created_at, id)` | `older_than=(created_at, id)` from an opaque `encode_cursor`; `decode_cursor` raises `BadCursor` | nothing skipped or repeated, 20 rows a page, deep p99 ~3 ms; every goal OK |

Goals, judged per incident: baseline ok (pages answered before), skipped = 0, repeated = 0, deep
p99 < 25 ms (a walk's 10th page or later) and rows read per page ≤ 40 (all for the pages asked for
during the incident).

Two pictures: `lanes` (opens first) shows each page request flying to the API, coloured by the
rows the database read for it (white about a page, deeper orange for OFFSET's thousands), and what
came back at the door: green a right page, red one that skipped posts, purple one that repeated
posts; the gauge is the database's busy share. `cluster` shows the three API servers and the
database's 4 workers: each worker is coloured by the query it runs (a deep OFFSET keeps one deep
orange), and wrong pages fly back red or purple; press `v` to switch.

- **Why OFFSET repeats and skips.** OFFSET 40 means "skip the first 40 rows *as they are now*".
  A post written at the top between two pages pushes everything down one place, so the next page
  starts with the last post you saw; a post deleted above you pulls everything up, and one post is
  never shown.
- **Why OFFSET is slow on deep pages.** The index cannot jump to row 20,000: the database walks it
  from the top and throws the rows away. The indexer's pages get slower the deeper it goes.
- **Why `created_at` alone is not enough.** It is not unique. A bulk import in one transaction
  stamps 600 posts with one `now()`: the page ends in the middle of them, and `< t` jumps past the
  rest (`<= t` would show them again, and a job could loop on them forever).
- **Why a cursor holds values.** A cursor that holds the last post's id and looks it up again
  breaks when that post is deleted (a purge): a 400, the client starts over, and repeats posts.
  `(created_at, id)` still says where to continue after the post is gone.
- **Why opaque.** Clients treat the cursor as a token, so you can change what is inside; a cursor
  that does not decode is a 400, never a 500 or some other page. To stop clients forging one, sign
  it (an HMAC).

"""Lab n_plus_one, in English: every word it shows. es.py has the same names and keys."""

from core.i18n import GoalText, IncidentText, StageText
from core.lessons import Lesson, Ref

TITLE = "N+1 queries"
SUMMARY = "A page asks the database once per item. Batch it, then join it, so pages stay fast."
PARAMS = {"rate": "pages opened per second"}

INCIDENT = IncidentText("Incident", "the incident", "the next incident")
VERBS = {"slow": "SLOW", "fast": "FAST", "big": "BIG", "normal": "NORMAL", "spike": "SPIKE", "calm": "CALM"}
CAUSES = {
    "backup": "a nightly backup is reading every table",
    "noisy_disk": "a noisy neighbour is saturating the disk",
    "zone_failover": "the primary failed over to another zone",
    "vacuum": "a long vacuum is running on the orders table",
    "flash_sale": "a flash sale: every shop has many more orders",
    "bulk_import": "a merchant bulk-imported their orders",
    "holiday_orders": "holiday season: order lists are long",
    "newsletter": "the newsletter just went out",
    "tv_ad": "a TV ad sent everyone to the site",
    "bot_crawl": "a search bot is crawling every page",
}

STAGES = [
    StageText("N+1",
              "Challenge: each page sends one query per order. Fetch all its customers in one query.",
              "Stage 1: one fetch_customers(ids) per page (IN)"),
    StageText("Batched",
              "Challenge: 2 round trips per page; when the database slows, pages crawl. Join them.",
              "Stage 2: one fetch_orders_with_customers per page (JOIN)"),
    StageText("Joined",
              "Solved: one query per page, so a slow database costs one round trip, not dozens.",
              "All stages done"),
]

GOALS = {
    "baseline": GoalText("Baseline ok", "load_page must return rows"),
    "queries": GoalText("Queries/page ≤ 2", "fetch customers in one IN"),
    "busy": GoalText("DB busy < 90%", "send fewer queries"),
    "p99": GoalText("p99 page < 40ms", "one JOIN: one round trip"),
    "served": GoalText("Served ≥ 99%", "pages must keep working"),
}

LEGEND = {"idle": "idle", "list": "list query", "per_item": "one per order", "batch": "IN batch",
          "join": "join", "served": "served", "failed": "gave up", "incident": "incident"}

STRINGS = {
    # incidents
    "title_slow_db": "Slow database",
    "title_big_pages": "Big pages",
    "title_spike": "Spike",
    "slow_db": "is slow, +{ms:.0f} ms a round trip: {cause}",
    "slow_db_end": "is fast again",
    "big_pages": "pages are {times:.0f}x longer: {cause}",
    "big_pages_end": "pages are back to normal",
    "spike": "gets {times:.0f}x the pages: {cause}",
    "spike_end": "traffic is back to normal",
    "warn_busy": "database {busy:.0%} busy",
    # the panel
    "tile_queries": "Q/page",
    "tile_p99": "p99",
    "tile_busy": "DB busy",
    "toplist": "Queries",
    "bar_pages": "Pages",
    "bar_queries": "Queries",
    "head_slow": "Slow DB: {qpp:.1f} queries a page, p99 {p99}",
    "head_busy": "Database {busy:.0%} busy: pages wait",
    "head_calm": "{qpp:.1f} queries per page",
    "note": "Dots: queries of 1 page in 4 (cosmetic speed).",
    # errors in your code
    "stuck": "a page has been loading for over {seconds:.0f} s: does load_page wait forever?",
}

LESSON = Lesson(
    title="N+1 queries",
    one_liner="A page that asks the database once per item makes N+1 round trips; batch or join them into one or two.",
    learn=(
        "The N+1 problem: load a list (1 query), then for each of its N items load something related "
        "(N queries). It looks harmless in code (an ORM attribute access in a loop) and in a quiet "
        "development database, where a round trip costs a fraction of a millisecond.",
        "In production every query is a round trip: the network, a connection from the pool, the "
        "database's own work. 30 pages/s with 20 items each is 630 queries/s where 60 would do; when the "
        "database slows down, every one of those round trips gets slower, and the pages time out.",
        "Batching: collect the ids and ask once (WHERE id IN (...)): 2 queries per page, whatever N is. "
        "ORMs call it eager loading: Django's prefetch_related, Rails' includes, SQLAlchemy's selectinload.",
        "Joining: let the database put orders and customers together in one query (Django's "
        "select_related, a JOIN): 1 round trip per page. It matters most when round trips are slow.",
        "Running the N queries concurrently (asyncio.gather) hides the latency a little but sends just as "
        "many queries: the database still drowns.",
    ),
    watch_for=(
        "N+1: deep orange dots, ~21 queries per page; a slow database saturates its 8 connections.",
        "Batched: 2 queries per page and the database is nearly idle, but pages need 2 slow round trips.",
        "Joined: 1 query per page; even with a slow database a page takes one round trip.",
        "Big pages (a sale) hurt N+1 the most: the query count grows with the list.",
    ),
    build=(
        ("Django: eager loading",
         "orders = Order.objects.filter(shop=shop).select_related('customer')   # JOIN\n"
         "orders = Order.objects.filter(shop=shop).prefetch_related('items')    # IN batch"),
        ("SQL: the two fixes",
         "SELECT * FROM customers WHERE id IN (17, 42, 99);\n"
         "SELECT o.*, c.name FROM orders o JOIN customers c ON c.id = o.customer_id\n"
         " WHERE o.shop_id = 7;"),
        ("Find it in production: count queries per request",
         "# log len(connection.queries) per request (Django), or use the ORM's N+1 detector\n"
         "# (Bullet for Rails, nplusone for Python) in tests"),
    ),
    checklist=(
        "Count queries per request in tests; fail the test when a list makes one query per item.",
        "Load related data eagerly (JOIN or IN) whenever you render a list.",
        "Watch round trips, not just query time: a fast query sent 100 times is a slow page.",
        "Paginate long lists: N grows with the data.",
        "For GraphQL or nested resolvers, batch per request with a DataLoader.",
    ),
    refs=(
        Ref("Django: select_related and prefetch_related",
            "https://docs.djangoproject.com/en/5.1/ref/models/querysets/#select-related",
            "Eager loading with a JOIN or with a second, batched query."),
        Ref("Rails guides: Eager loading associations",
            "https://guides.rubyonrails.org/active_record_querying.html#eager-loading-associations",
            "includes, preload and eager_load, and the N+1 problem they solve."),
        Ref("SQLAlchemy: Relationship loading techniques",
            "https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html",
            "lazy, joined and selectin loading."),
        Ref("GraphQL DataLoader",
            "https://github.com/graphql/dataloader",
            "Batching and caching per request for nested resolvers."),
    ),
    try_next=(
        "Do stage 1 in labs/n_plus_one/main.py and watch the queries per page drop to 2.",
        "Then wait for a slow database: why are pages still over 40 ms?",
        "Do stage 2 and compare the p99 during the next slowdown.",
        "Try asyncio.gather on the N queries: does the database like it better?",
    ),
)

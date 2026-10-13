from core.lessons import Lesson, Ref

LESSON = Lesson(
    title="Rate limiting",
    one_liner="A few noisy clients can take an API down for everyone. A rate limiter keeps each one to its share.",
    learn=(
        "Without a limit, a backend shares its capacity with whoever asks loudest. A batch job, a "
        "scraper or a retry loop on a few accounts fills the queue, and every other client's "
        "requests fail with theirs.",
        "Fixed window: count each client's requests per second (or minute) and refuse the rest. "
        "Simple and cheap, but a burst at the end of one window and the start of the next gets "
        "twice the limit through in a moment.",
        "Token bucket: each client has a bucket that refills at the allowed rate, up to a burst "
        "size; every request takes a token. No edges to game, and short bursts are still fine.",
        "A per-client limit is a promise to each client. Add them up and they can promise far more "
        "than the backend can do. A fair share caps each client at capacity / active clients, "
        "so the backend is never promised more than it has.",
    ),
    watch_for=(
        "No limit: during a flood the backend turns requests away (red), and the clients that did "
        "nothing wrong fail too.",
        "Fixed window: the flood is capped, but its peak hits 2x the limit when a burst straddles a reset.",
        "Token bucket: the peak is smooth, yet several capped clients together still overload the backend.",
        "Fair share: the flooding clients are turned away (dark orange) and everyone else is served.",
    ),
    build=(
        ("Redis: a token bucket shared by many API servers (one atomic script per request)",
         "local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens') or ARGV[2])\n"
         "local last = tonumber(redis.call('HGET', KEYS[1], 'last') or ARGV[3])\n"
         "tokens = math.min(ARGV[2], tokens + (ARGV[3] - last) * ARGV[1])\n"
         "local ok = tokens >= 1\n"
         "if ok then tokens = tokens - 1 end\n"
         "redis.call('HSET', KEYS[1], 'tokens', tokens, 'last', ARGV[3])\n"
         "return ok"),
        ("NGINX: a leaky bucket per client IP",
         "limit_req_zone $binary_remote_addr zone=api:10m rate=20r/s;\n"
         "location /api/ { limit_req zone=api burst=10 nodelay; }"),
    ),
    checklist=(
        "Limit per client (API key, account, IP), not only globally.",
        "Use a token bucket or a sliding window, not a plain fixed window.",
        "Return 429 with Retry-After, so well-behaved clients back off.",
        "Make sure the per-client limits cannot add up to more than the backend can do.",
        "Limit at the edge (gateway) and in the service, and alert on the share of 429s.",
    ),
    refs=(
        Ref("Stripe: Scaling your API with rate limiters",
            "https://stripe.com/blog/rate-limiters",
            "Request rate limiters, concurrency limiters and load shedders, as Stripe runs them."),
        Ref("Cloudflare: How we built rate limiting capable of scaling to millions of domains",
            "https://blog.cloudflare.com/counting-things-a-lot-of-different-things/",
            "Why fixed windows let bursts through, and a cheap sliding window."),
        Ref("Token bucket (Wikipedia)",
            "https://en.wikipedia.org/wiki/Token_bucket",
            "The algorithm, and how it relates to the leaky bucket."),
        Ref("NGINX: Rate Limiting with NGINX",
            "https://blog.nginx.org/blog/rate-limiting-nginx",
            "limit_req, burst and nodelay, with examples."),
        Ref("Envoy: global rate limiting",
            "https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/other_features/global_rate_limiting",
            "Local token buckets in each proxy plus a shared limit service."),
    ),
    try_next=(
        "Do stage 1 in labs/rate_limit/main.py and watch the flood get turned away.",
        "Do stage 2 and watch the Peak goal turn green.",
        "Do stage 3 and watch the other clients stay at 100% while a flood hits.",
    ),
)

# Lab: webhook delivery

*[Leer en español](es/README.md)*

A shop platform sends webhooks to 20 customer endpoints: every order makes `order.created`, then
`order.paid` (0.05–2 s later), `order.fulfilled` (4–15 s later) and sometimes `order.refunded`,
~60 events a second in all; endpoint #1 is the biggest customer. 24 delivery workers share the
work: a free worker asks your `Dispatcher.next(now)` what to send, POSTs it, and reports the
answer with `Dispatcher.done(ev, status, now)`. A healthy endpoint answers 200 in ~60 ms. At
random times, like in production, an endpoint goes down (their deploy answers 503, an expired
TLS certificate, a crash loop), its connections hang with no answer (a DNS change points at an
old IP, a firewall drops our packets), it gets slow (their database is struggling: 2.5–8 s per
answer), it answers 500 forever to a few malformed events, or a sale makes a burst of 2–3x the
events. The run never restarts. The first incident is always endpoint #1 hanging at 0:20–0:45.

```
uv run python -m live webhook_delivery          # watch it; edit main.py and save
uv run python -m live webhook_delivery --lesson # the concept, links and a checklist
uv run pytest labs/webhook_delivery             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

Three pictures (`v` switches): **fanout** (it opens with this one) shows new events flying from
the shop to the dispatcher in the middle, its gauge the share of the 24 workers busy (red while half
of them or more are stuck on one endpoint), and five of the 20 endpoints on the right, the one in
trouble first. An endpoint is red while down, pink while it hangs, orange while slow, purple while
it gets malformed events (poison); its gauge is the workers busy with it. Attempts fly white the
first, oranges for retries; one still waiting for an answer stays near its endpoint; answers fly
back green (deep orange when out of order), failures die in red. **cluster** shows the dispatcher
(left, middle) between four worker nodes of six workers each, and the 20 endpoints in four columns
(#1–#5 in the first), in the same colours; a worker node turns orange as its workers fill up, the
dispatcher orange, then red, as its backlog grows, and events given up fly back to the shop in
purple. **lanes** shows every event waiting for delivery as a circle, the dispatcher as the door
and the 24 workers as the server, its gauge the share busy.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Fire once (given) | one shared queue; a failed POST is given up; no timeout (the client's 30 s) | when #1 hangs, its events are lost (purple) and every worker ends up waiting on it: the other 19 endpoints starve |
| 1 Retries | `timeout = ATTEMPT_TIMEOUT`; `backoff` (full jitter, 0.5 s doubling, capped at 30 s); `retry` pushes a failure onto a heap that `next` serves first | nothing lost; but #1's timeouts and retries still fill the shared pool (the healthy p99 goes to seconds), and once an endpoint is back its events arrive out of order |
| 2 Queue per endpoint | `Endpoint.pick/succeeded/failed`: a queue per endpoint, at most `MAX_IN_FLIGHT` (4) POSTs each, one event per order at a time, oldest first; after `DISABLE_AFTER` (5) failures in a row park it: one probe every 5 s with a fresh event, and replay the backlog once it answers; give up an event after `MAX_ATTEMPTS` only while the endpoint works (poison) | at most 4 workers wait on #1, then none; the others never notice; every goal OK |

Goals, judged per incident on the events made during it and 5 s after: baseline ok (before),
lost = 0 (events given up, or not delivered 35 s after the window; malformed events aside: they
can never be delivered), out of order = 0 (an event delivered while an earlier event of its
order was still pending), the p99 from made to delivered < 1 s for the healthy endpoints (all
but the one in trouble), and wasted work ≤ 10% (the workers' time spent on attempts that failed).

- **Why a timeout first.** Without one, a POST to an endpoint whose packets are dropped waits
  for the HTTP client's default. Retries without a timeout lose nothing, but each try holds a
  worker for 30 s.
- **Why isolation.** A shared pool is shared fate: one dead customer's timeouts and retries
  take the workers from the 19 healthy ones. A queue and a cap per endpoint (a bulkhead) keep
  the damage to its share.
- **Why order per key, and why it needs a way out.** Retries reorder: `order.paid` succeeds
  while `order.created` waits for its retry. One event per order in flight, oldest first, fixes
  it; but a malformed event that fails forever would then block its order forever: give it up
  after a few attempts, while the endpoint is otherwise working (the customer can replay it).
- **Why park.** A capped dead endpoint still costs its 4 workers for every timeout. Parking it
  after N failures in a row (a circuit breaker) costs one probe every few seconds instead, and
  replaying its backlog in order when it answers again loses nothing.
- **Not simulated, but do it:** sign each webhook with an HMAC-SHA256 of the timestamp and the
  body (a secret per endpoint), and send an event id: at-least-once delivery means a POST that
  timed out may have been processed, and the customer must drop the duplicate.

# Lab: canary_releases

*[Leer en español](es/README.md)*

Users send ~200 requests/s to four endpoints (`/home` 55%, `/search` 25%, `/cart` 15%, `/pay` 5%).
A **router** spreads them over 20 instances running the **live build** (~0.3% errors, p99 ~160 ms).
Every couple of minutes the team ships a new build: a **release**. You write the release controller.

For each release the scenario makes a `Release()` and calls `release.decide(metrics)` at once and then
every 5 s; you return the share of the traffic the new build gets (0 to 1). The router sends that share
of the requests, at random, to the new build (the **canary**) and the rest to the live build (the
**baseline**). `1.0` makes the new build live everywhere; `0.0` rolls it back. The metrics count each
build's requests, errors and slow answers (> 250 ms) since the router last changed its split, in
total and per endpoint, so the canary and the baseline are always compared over the same seconds.

Most builds are fine. Some are bad, each in its own way, like in production: a **crash loop** (50-80%
of its requests fail at once: a setting missing in production, a config typo, out of memory at start),
an **error regression** (0.3% errors become ~3%: an unhandled edge case, a timeout set too short), a
**slow build** (a new N+1 query, synchronous logging, a cache key bug: +150-250 ms on a quarter of
the requests, and no errors at all), or a **bug on /pay** only (a rounding change, a coupon parser:
15-30% of payments fail, 5% of the traffic). And sometimes a good build ships while a **dependency
flakes** (a database failover, a DNS blip, a slow payment provider): errors (10-20%, in bursts) and slow
answers go up on both builds. A bad build that reaches 100% stays live until someone on call rolls it
back by hand, 2 minutes after the deploy. The first release is always a **slow build at 0:20**. The
run never restarts.

```
uv run python -m live canary_releases            # watch it; edit main.py and save
uv run python -m live canary_releases --lesson   # the concept, links and a checklist
uv run pytest labs/canary_releases               # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

| Stage | In `main.py` | What you see (the first release, the slow build) |
|---|---|---|
| 0 Everywhere at once (given) | `decide` returns 1.0 | every user gets it: 25% of all requests hurt for 2 minutes (p99 ~330 ms instead of ~160 ms), until the manual rollback |
| 1 Fixed canary | `fixed_canary(m)`: 5%, roll back above 5% errors, everywhere after 60 s | a purple trickle to one instance; no errors, so after 60 s it goes live: 11-12% hurt. It undoes a crash loop in 5 s, but lets most error regressions (9 of 14) and /pay bugs (18 of 19) go live, and rolls back 24 of 25 good builds shipped during a flaky dependency |
| 2 Staged canary | `z_score`, `worse(canary, baseline)`, `ramp(m)`: errors and slow vs the baseline, in total and per endpoint, at least 5 bad answers and z > 4, steps 5% → 25% → 50% → 100% of 20 s and 200 samples | the slow build is undone from 5% after 5 s (0.04-0.1% hurt); good builds reach 100% in ~65 s, flaky dependency or not; every bad build is undone (the /pay bug at 25%) |

Goals, judged per release: baseline ok (≤ 1% errors before the deploy), hurt ≤ 0.5% (requests the
new build failed or slowed, over every request of the 2-minute release window), bad builds at 100% =
0, false alarms = 0 (good builds rolled back) and rollout ≤ 90 s (from the deploy to 100%, good builds
only). The stage is judged from the first release: a router that never split the traffic is stage 0;
a canary that missed a goal is stage 1.

Why each part of stage 2 matters (measured over 20 seeds, 20 minutes each): comparing errors only lets
every slow build through; comparing the total only lets 4 of 19 /pay bugs reach 100% (diluted: +1.5%
errors in the total); a bar of 3 standard errors instead of 4 rolls back 4 of 25 good builds shipped
during a flaky dependency (10 tests every 5 s cross it by chance); and no minimum count (blaming one
bad answer) rolls back 6 of 15 plain good builds.

**The pictures.** The window opens on the lanes: users (orange the longer they wait: a slow build
shows here) → the router (the door: dotted purple while it splits the traffic, shut red while many
requests fail) → the fleet as one server, its gauge the new build's share (purple) or full blue when
everyone is on the live build, its outline red while a build hurts requests; requests to the canary
are the big purple dots. Under it: `LIVE v100`, `CANARY v102 25%`, `ROLLED BACK v101` or `BAD BUILD
LIVE`. Press `v` (or `--view cluster`) for the instances: blue on the live build, purple on the canary
(as many as its share: 1 of 20 at 5%), red while their build fails requests, orange while it slows
them; requests fly to the instance that got them. The chart shows requests each second by the build
that answered them (blue live, purple canary), slow ones orange and failed ones red on top. During a
release the headline compares the live build with the canary: `errors 0.3%→3.1% · slow 0.2%→0.1%`.

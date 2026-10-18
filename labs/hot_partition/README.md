# Lab: hot partition

*[Leer en español](es/README.md)*

A key/value store is sharded over six partitions (p0 ... p5) by a hash of the key, like DynamoDB,
Cassandra or a sharded Redis; each partition serves 150 requests a second and throttles when its
queue holds more than 0.2 s of work. Users like, click and view things: ~120 operations a second
on counters (60% reads of a count, 40% increments) over 5,000 keys with a Zipf-like popularity,
all through your `Counters` (`incr(key)`, `read(key)`). Each partition is ~15% busy.

At random times, like in production, one key explodes: a celebrity's post goes viral (likes),
a newsletter link is clicked by everyone (clicks), a flash sale sells one product (sales, and its
page reads the count), or a bot hammers one id (reads). 200–400 operations a second on one key:
more than its partition can serve, while the other five idle. Its traffic ramps up in 1.5 s,
holds for 5–22 s, then drops to a tail that lasts a minute. The run never restarts. The first
incident is always a viral post at 0:20–0:32.

```
uv run python -m live hot_partition          # watch it; edit main.py and save
uv run python -m live hot_partition --lesson # the concept, links and a checklist
uv run pytest labs/hot_partition             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

Three pictures (`v` switches): **fan-out** (it opens with this one) shows the users' operations
reaching your `Counters` (the relay in the middle), which sends requests to the six partitions on
the right, p0 … p5, each with its utilisation beside its name (`p1 99%`) and in its gauge (orange
from 70%, red from 90%, when it throttles); the hot key's partition is purple, one over 90% red.
Requests fly white (a usual one), purple (one on the hot key), orange (an extra request of a read
fanning in over sub-keys) or blue (folding sub-keys back); a throttled one stops half way, red. The
relay's gauge is the fan-in requests it makes a second. **cluster** shows the six partitions as
nodes, coloured by utilisation (blue under 50%, oranges busy, red over 90%), with the same requests
flying from the users to them. **lanes** shows the users' operations on the left, your `Counters` as
the door and the store as the server, its gauge the busiest partition's utilisation; answers are
green (one request), orange (fanned in), blue (from the cache) or red (throttled).

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Hash by key (given) | every operation goes to the key itself | one node turns red, purple dots pour into it and die in red; the others stay blue |
| 1 Salted hot keys | `heat` counts each key's writes over the last 0.25 s; at `HOT` writes/s `salt` it: writes go to one of six sub-keys at random (`pick`), and `keys_of` names all six, so `read` adds them up | the viral post's writes spread over all six partitions; but every read of it now costs six requests (orange), and it stays salted after it cools; a bot (reads only) still melts its partition |
| 2 Adaptive salting | `salts_for`: N from the heat; cache a read-hot or salted key's count for 0.5 s; `cool`: once under `COOL` writes/s for 2 s, write to the key itself, and `fold` the sub-keys back after 1 s | the key spreads only while it is hot, the bot's reads come from the cache, and once it cools the orange stops; every goal OK |

Goals, judged per incident: the busiest partition under 90% (its utilisation on average while the
key is hot, from 1 s in), throttled ≤ 1% and p99 ≤ 100 ms (operations from the start to 5 s after
the end), lost increments = 0 (every half second, what the store holds in the keys `keys_of` names
must add up to exactly the increments acknowledged; a count in flight while it is folded is only
missing for an instant), and requests per operation ≤ 1.1x after it cools (8–18 s after the end,
while the key still has a tail of views).

- **Why salting hurts reads.** A salted key's count is spread over N sub-keys, so a read must ask
  all N: salting the key a bot is reading multiplies its load by six instead of spreading it. Hot
  reads want a cache: a like count half a second old is fine.
- **Why fold back.** A key stays popular-ish long after it stops being viral. Salted for good, every
  one of its reads costs six requests forever; with many past viral posts, the fan-in adds up.
- **Why wait before folding.** A write sent to `key#3` just before you stopped salting may still
  be on its way. Take `key#3`'s count too early and that write lands after it: lost. Stop writing to
  the sub-keys first, wait for writes in flight, then move the counts.
- **Why the width only grows.** If N goes from 3 to 6 and then back to 4, sub-keys 4 and 5 still
  hold counts: a read of only four sub-keys loses them.

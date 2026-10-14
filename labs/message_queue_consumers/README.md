# Lab: message queue consumers

*[Leer en español](es/README.md)*

Producers send ~40 jobs a second to a queue like Amazon SQS. Seven worker processes receive
them, six at a time each, and call your `Consumer.process(msg)`. A received message is hidden
from the other workers for its visibility timeout (2 s); if it is not deleted (acked) by then,
the queue hands it to another worker. A job takes ~0.1 s. At random times, like in production,
worker processes crash mid-job and restart 2 s later (a deploy, an OOM kill, spot instances
taken back), a downstream gets slow so 10% of jobs take 2.5–5 s (longer than the visibility
timeout), a bad producer deploy sends poison messages that always fail (each try hangs 2.5 s,
then fails), or the downstream blips (every call fails for 1–3 s). The run never restarts. The
first incident is always a poison batch at 0:20–0:30.

```
uv run python -m live message_queue_consumers          # watch it; edit main.py and save
uv run python -m live message_queue_consumers --lesson # the concept, links and a checklist
uv run pytest labs/message_queue_consumers             # x = not yet, X = done
```

In Spanish (`--lang es` or `LABS_LANG=es`), you edit `es/main.py` instead: the same code, with
Spanish comments and hints.

Two pictures (`v` switches): **cluster** (it opens with this one) shows the queue (left), the
seven worker processes around it and the dead-letter queue (right) as nodes: deliveries fly to
the workers, acks fly back (green), parked messages fly to the DLQ (purple), lost jobs die in
red, and a crashed process turns red. **lanes** shows every message in the queue as a circle,
the queue as the door and the worker pool as the server, its gauge the share of slots busy.

| Stage | In `main.py` | What you see |
|---|---|---|
| 0 Ack on receipt (given) | `delete`, then `handle` | crashes, failed jobs and poison lose jobs (red); the DLQ stays empty |
| 1 Ack after work | start `heartbeat` as a task, `handle`, then `delete`; cancel the heartbeat in `finally`; a failed job just returns | nothing lost, slow jobs are not handed to a second worker; but poison comes back forever: the oldest message keeps getting older, and after a few poison batches the workers are busy with poison and the queue backs up |
| 2 Retries + DLQ | on `JobFailed`, `on_failure`: hide it for `backoff(receive_count)` (1, 2, 4 s… with jitter), and after `MAX_RECEIVES` deliveries `dlq.send` and `delete` | poison is parked after 4 tries (purple), a short blip parks nothing; every goal OK |

Goals, judged per incident: baseline ok (before), lost = 0, duplicates ≤ 1% (jobs worked on by
two workers at once, or again after they were done), queue age p99 < 1 s (how long a message
waits before a worker first takes it), all for jobs sent during the incident and 5 s after;
and "DLQ: poison only": every poison message parked, and no good job parked (after; "none" when
there was no poison).

- **Why the heartbeat.** Ack after the work alone means a job slower than the visibility timeout
  comes back while its first worker is still on it: a second worker starts it too (the Dups tile).
  Raising the timeout for every message would also work, but then a crashed worker's messages
  wait that long to come back. A heartbeat keeps the timeout short and the slow jobs hidden.
- **Why backoff, and why bounded.** Without a limit, a poison message is retried forever. Without
  backoff, a limit parks good jobs too: when the downstream blips for a second, four tries in
  0.3 s all fail and a good job lands in the DLQ. Backoff spreads the tries past the blip.
- **Duplicates still happen.** A worker that crashes after the work and before the ack leaves a
  job that will run again. At-least-once means the jobs themselves must be idempotent.

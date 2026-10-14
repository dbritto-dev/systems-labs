"""Lab message_queue_consumers: YOUR FILE. Edit it and save; the live window reruns it.

Producers send ~40 jobs a second to a queue like Amazon SQS. Seven worker processes receive
them, six at a time each, and call `Consumer.process(msg)` for every message. A received
message is invisible to the other workers for VISIBILITY seconds (the visibility timeout);
if it is not deleted by then, the queue hands it to another worker.

Right now `process` deletes (acks) the message the moment it arrives, then does the job. When
a worker process crashes mid-job (a deploy, an OOM kill), or the job fails, the job is lost.

Do the stages in order, in this file:

  Stage 1  Ack after the work: delete the message only once `handle(msg)` has succeeded, so a
           crash or a failure leaves it in the queue for another worker. While you work, keep
           it hidden: `heartbeat(msg)` extends its visibility every HEARTBEAT seconds, so a slow
           job is not handed to a second worker while the first is still on it.
  Stage 2  Bounded retries and a dead-letter queue: when a job fails, `on_failure(msg)` hides
           the message for `backoff(receive_count)` seconds (longer each time, with jitter); once
           it has been delivered MAX_RECEIVES times it is poison: park it in the DLQ and delete
           it, so it stops coming back.

What you get (see labs/message_queue_consumers/api.py):
  msg.id, msg.receive_count                    receive_count is 1 on the first delivery
  await self.queue.delete(msg) -> bool         ack: remove the message for good
  await self.queue.change_visibility(msg, s)   hide it for s more seconds -> bool (False: it
                                               is gone or another worker has it now)
  await self.dlq.send(msg)                     park it in the dead-letter queue
  await self.handle(msg)                       do the job; raises JobFailed when it fails

Check yourself:  uv run pytest labs/message_queue_consumers
Peek at a solution (after trying!):  labs/message_queue_consumers/reference.py
"""

from __future__ import annotations

import asyncio
import random

from labs.message_queue_consumers.api import VISIBILITY, JobFailed, Message

HEARTBEAT = 0.5  # seconds between heartbeats: well inside the visibility timeout
MAX_RECEIVES = 4  # deliveries before a message is parked in the DLQ
BACKOFF_BASE = 1.0  # seconds before the 2nd delivery; doubles each time
BACKOFF_CAP = 8.0


class Consumer:
    """Works on the messages of one worker process.

    Contract:
      - `await consumer.process(msg)` is called once per delivery. Return when you are done with
        this delivery (the job succeeded and was acked, or it failed and you dealt with it).
      - A job must never be lost: ack (delete) only after `handle(msg)` succeeded.
      - A job should not be worked on by two workers at once: keep the message hidden while
        `handle` runs.
      - A message that keeps failing must end up in the DLQ, not in the queue forever.
    """

    def __init__(self, queue, dlq, handle, rng: random.Random | None = None) -> None:
        self.queue = queue
        self.dlq = dlq
        self.handle = handle
        self.rng = rng or random.Random(0)  # for backoff(): runs repeat

    async def process(self, msg: Message) -> None:
        # Stage 1: start the heartbeat as a task, `beat = asyncio.ensure_future(self.heartbeat(msg))`,
        #          then `await self.handle(msg)`, and only then `await self.queue.delete(msg)`.
        #          Cancel the heartbeat when you are done, also when the job fails or the process
        #          crashes (`try: ... finally: beat.cancel()`). A failed job: just return; the
        #          message comes back when its visibility timeout runs out.
        # Stage 2: when handle raises JobFailed, cancel the heartbeat and `await self.on_failure(msg)`.
        await self.queue.delete(msg)  # ack on receipt: if we crash or fail now, the job is gone
        try:
            await self.handle(msg)
        except JobFailed:
            pass

    async def heartbeat(self, msg: Message) -> None:
        """Stage 1. Every HEARTBEAT seconds, `await self.queue.change_visibility(msg, VISIBILITY)`
        so the message stays hidden while you work. Stop when it returns False (the message is
        gone, or another worker has it now). It runs until it is cancelled."""
        raise NotImplementedError("TODO stage 1: heartbeat(msg)")

    async def on_failure(self, msg: Message) -> None:
        """Stage 2. The job failed. If `msg.receive_count >= MAX_RECEIVES`, it is poison:
        `await self.dlq.send(msg)`, then delete it from the queue. Otherwise hide it for
        `backoff(msg.receive_count, self.rng)` seconds, so it is retried later."""
        raise NotImplementedError("TODO stage 2: on_failure(msg)")


def backoff(receive_count: int, rng: random.Random | None = None) -> float:
    """Stage 2. Seconds to wait before the next delivery: BACKOFF_BASE doubled for every
    delivery so far (1, 2, 4 ... for receive_count 1, 2, 3 ...), at most BACKOFF_CAP, with
    "equal jitter": half of it fixed, the other half a random amount (`(rng or random).uniform`).

    >>> 0.5 <= backoff(1, random.Random(1)) <= 1.0
    True
    """
    raise NotImplementedError("TODO stage 2: backoff(receive_count)")

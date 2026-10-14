"""Lab message_queue_consumers: a working solution. Read it after you have tried main.py."""

from __future__ import annotations

import asyncio
import random

from labs.message_queue_consumers.api import VISIBILITY, JobFailed, Message

HEARTBEAT = 0.5  # seconds between heartbeats: well inside the visibility timeout
MAX_RECEIVES = 4  # deliveries before a message is parked in the DLQ
BACKOFF_BASE = 1.0  # seconds before the 2nd delivery; doubles each time
BACKOFF_CAP = 8.0


class Consumer:
    def __init__(self, queue, dlq, handle, rng: random.Random | None = None) -> None:
        self.queue = queue
        self.dlq = dlq
        self.handle = handle
        self.rng = rng or random.Random(0)

    async def process(self, msg: Message) -> None:
        # Keep the message hidden while we work on it, however long the job takes.
        beat = asyncio.ensure_future(self.heartbeat(msg))
        try:
            await self.handle(msg)
        except JobFailed:
            beat.cancel()
            await self.on_failure(msg)
            return
        finally:
            beat.cancel()  # also when this process crashes mid-job
        await self.queue.delete(msg)  # ack only once the work is done

    async def heartbeat(self, msg: Message) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT)
            if not await self.queue.change_visibility(msg, VISIBILITY):
                return  # gone, or someone else has it now

    async def on_failure(self, msg: Message) -> None:
        if msg.receive_count >= MAX_RECEIVES:  # it keeps failing: poison. Park it, out of the way.
            await self.dlq.send(msg)
            await self.queue.delete(msg)
        else:  # try again later, and later still each time
            await self.queue.change_visibility(msg, backoff(msg.receive_count, self.rng))


def backoff(receive_count: int, rng: random.Random | None = None) -> float:
    delay = min(BACKOFF_CAP, BACKOFF_BASE * 2 ** (receive_count - 1))
    return delay / 2 + (rng or random).uniform(0, delay / 2)  # equal jitter: never shorter than half

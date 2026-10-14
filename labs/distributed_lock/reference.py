"""Lab distributed_lock: a working solution (stage 2). Read it after you have tried main.py.

Leases: the lock service gives the lock for LEASE seconds and takes it back once that time is
up, so a holder that crashed or was cut off blocks everyone for at most LEASE. The holder
renews it every LEASE / 3 while its job runs.

Fencing tokens: every grant comes with a number one higher than the last. The worker sends it
with every write, and the storage refuses a write whose token is older than one it has already
seen. A holder that was paused, or whose write sat in the network, wakes up with an old token,
and its late write bounces off the storage instead of overwriting newer data.
"""

from __future__ import annotations

import asyncio

from core.net import Message, Node, RPCError

LOCK, STORAGE = "lock", "storage"
LEASE = 2.0  # seconds a grant lasts unless renewed
RETRY = 0.1  # seconds between tries while the lock is taken
GIVE_UP = 8.0  # a job stops waiting for the lock after this long
PARTS = 3  # a job writes the report in this many parts
WORK = 0.1  # seconds of work before each part
WRITE_TIMEOUT = 0.5  # seconds to wait for the storage to answer a write


async def compute(job: int, part: int) -> str:
    """The work before each write: build one part of the report. (Given: do not change.)"""
    await asyncio.sleep(WORK)
    return f"report {job}, part {part + 1} of {PARTS}"


class LockService(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.holder = None  # the job that holds the lock
        self.expires = 0.0  # when its lease runs out
        self.token = 0  # the token of the last grant

    def free(self) -> bool:
        return self.holder is None or self.now() >= self.expires

    async def on_acquire(self, msg: Message) -> None:
        job = msg.body["job"]
        if not self.free() and self.holder != job:
            self.reply(msg, {"type": "error", "code": 11, "text": "the lock is taken"})
            return
        self.holder, self.expires = job, self.now() + LEASE
        self.token += 1
        self.reply(msg, {"type": "acquire_ok", "token": self.token, "lease": LEASE})

    async def on_renew(self, msg: Message) -> None:
        if self.holder != msg.body["job"] or self.free():
            self.reply(msg, {"type": "error", "code": 22, "text": "the lease is gone"})
            return
        self.expires = self.now() + LEASE
        self.reply(msg, {"type": "renew_ok", "lease": LEASE})

    async def on_release(self, msg: Message) -> None:
        if self.holder == msg.body["job"]:
            self.holder = None


class Worker(Node):
    async def on_job(self, msg: Message) -> None:
        job = msg.body["job"]
        token = await self.acquire(job)
        if token is None:
            self.reply(msg, {"type": "error", "code": 11, "text": "never got the lock"})
            return
        renewing = self.spawn(self.renew(job))
        try:
            for part in range(PARTS):
                data = await compute(job, part)
                await self.rpc(STORAGE, {"type": "write", "job": job, "part": part, "data": data,
                                         "token": token}, timeout=WRITE_TIMEOUT)
            self.reply(msg, {"type": "job_ok"})
        except (TimeoutError, RPCError):
            self.reply(msg, {"type": "error", "code": 11, "text": "a write failed"})
        finally:
            renewing.cancel()
            self.send(LOCK, {"type": "release", "job": job})

    async def acquire(self, job: int):
        """The fencing token of a fresh grant, or None after GIVE_UP seconds without one."""
        give_up = self.now() + GIVE_UP
        while self.now() < give_up:
            try:
                reply = await self.rpc(LOCK, {"type": "acquire", "job": job}, timeout=0.5)
                return reply["token"]
            except (TimeoutError, RPCError):
                await self.sleep(RETRY)
        return None

    async def renew(self, job: int) -> None:
        """Keep the lease while the job runs (a refused renewal ends the loop)."""
        while True:
            await self.sleep(LEASE / 3)
            await self.rpc(LOCK, {"type": "renew", "job": job}, timeout=0.5)


class Storage(Node):
    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.report: dict[int, str] = {}  # part -> its text
        self.highest = 0  # the newest fencing token seen

    def is_stale(self, token) -> bool:
        """A write without a token, or with one older than the newest seen, comes from a lost lock."""
        return token is None or token < self.highest

    async def on_write(self, msg: Message) -> None:
        token = msg.body.get("token")
        if self.is_stale(token):
            self.reply(msg, {"type": "error", "code": 22, "text": f"token {token} is older than {self.highest}"})
            return
        self.highest = token
        self.report[msg.body["part"]] = msg.body["data"]
        self.reply(msg, {"type": "write_ok"})

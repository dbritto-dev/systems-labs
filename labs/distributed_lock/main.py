"""Lab distributed_lock: YOUR FILE. Edit it and save; the live window reruns it.

Four workers share one report in a storage service, and only one job may write it at a time,
so a job first takes a lock from a lock service. Clients hand out jobs (~0.8 a second) to any
worker; the worker takes the lock, writes the report in PARTS parts, releases it and answers.
Every message takes ~50 ms. Right now the lock never expires, so a holder that freezes,
crashes or is cut off from the lock service blocks every other job, maybe forever.

Do the stages in order, in this file:

  Stage 1  Leases: the lock service gives the lock for LEASE seconds and takes it back when the
           lease runs out; the holder renews it every LEASE / 3 while its job runs. Now nobody
           waits more than a couple of seconds for a dead holder. But a holder that was frozen
           (a GC pause) wakes up still thinking it holds the lock, and writes over the work of
           the job that got the lock after it.
  Stage 2  Fencing tokens: every grant comes with a number, one higher each time. The worker
           sends it with every write, and the storage refuses a write whose token is older than
           the newest it has seen. A late write from a lost lock bounces off.

How your nodes talk (see core/net.py):
  self.node_id, self.node_ids        who you are, and every node
  self.reply(msg, {...})             answer a request
  self.send(dest, {...})             fire and forget
  await self.rpc(dest, {...}, timeout=0.5)   send and wait for the reply (TimeoutError if lost,
                                     RPCError for an error reply)
  self.spawn(coroutine)              run something in the background (returns a task you can .cancel())
  await self.sleep(seconds)          wait; self.now() is the clock (virtual time)

The checker watches the messages: which job got an `acquire_ok`, and which writes the storage
answered with `write_ok`. A write is *corrupt* when the storage accepts it after a job that got
the lock later has already written. Keep the message names below.

Check yourself:  uv run pytest labs/distributed_lock
Peek at a solution (after trying!):  labs/distributed_lock/reference.py
"""

from __future__ import annotations

import asyncio

from core.net import Message, Node, RPCError

LOCK, STORAGE = "lock", "storage"
LEASE = 2.0  # seconds a grant lasts unless renewed (stage 1)
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
    """Hands the lock to one job at a time.

    Contract:
      - `acquire` {job}  -> {"type": "acquire_ok"} (stage 2: with "token") if the job may have
                            the lock, else {"type": "error", "code": 11};
      - `renew` {job}    -> {"type": "renew_ok"} if the job still holds the lock, else an error
                            (stage 1);
      - `release` {job}  -> frees the lock if that job holds it (no answer).
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.holder = None  # the job that holds the lock
        # Stage 1: self.expires = 0.0, when the holder's lease runs out.
        # Stage 2: self.token = 0, the token of the last grant.

    async def on_acquire(self, msg: Message) -> None:
        # Stage 1: the lock is also free once self.now() >= self.expires. On a grant, set
        # self.expires = self.now() + LEASE. (The same job asking again may have it again.)
        # Stage 2: on a grant, self.token += 1 and put "token": self.token in the reply.
        job = msg.body["job"]
        if self.holder is not None:
            self.reply(msg, {"type": "error", "code": 11, "text": "the lock is taken"})
            return
        self.holder = job
        self.reply(msg, {"type": "acquire_ok"})

    async def on_renew(self, msg: Message) -> None:
        """Stage 1: if msg.body["job"] holds the lock and its lease has not run out, push
        self.expires to self.now() + LEASE and reply {"type": "renew_ok"}; otherwise reply
        {"type": "error", "code": 22} (the lease is gone: someone else may have the lock)."""
        raise NotImplementedError("TODO stage 1: LockService.on_renew")

    async def on_release(self, msg: Message) -> None:
        if self.holder == msg.body["job"]:
            self.holder = None


class Worker(Node):
    """Runs the jobs it is given: lock, write PARTS parts, unlock, answer.

    Contract:
      - `job` {job} -> {"type": "job_ok"} once every part is written, else an error;
      - write a part with an rpc to STORAGE: {"type": "write", "job", "part", "data"}
        (stage 2: and "token").
    """

    async def on_job(self, msg: Message) -> None:
        # Stage 1: once you hold the lock, keep it: renewing = self.spawn(self.renew(job)), and
        # renewing.cancel() in the finally.
        # Stage 2: put "token": token in every write.
        job = msg.body["job"]
        token = await self.acquire(job)
        if token is None:
            self.reply(msg, {"type": "error", "code": 11, "text": "never got the lock"})
            return
        try:
            for part in range(PARTS):
                data = await compute(job, part)
                await self.rpc(STORAGE, {"type": "write", "job": job, "part": part, "data": data},
                               timeout=WRITE_TIMEOUT)
            self.reply(msg, {"type": "job_ok"})
        except (TimeoutError, RPCError):
            self.reply(msg, {"type": "error", "code": 11, "text": "a write failed"})
        finally:
            self.send(LOCK, {"type": "release", "job": job})

    async def acquire(self, job: int):
        """Ask for the lock every RETRY seconds; return the grant's token (stage 2; 0 before
        tokens exist), or None after GIVE_UP seconds without the lock."""
        give_up = self.now() + GIVE_UP
        while self.now() < give_up:
            try:
                reply = await self.rpc(LOCK, {"type": "acquire", "job": job}, timeout=0.5)
                return reply.get("token", 0)
            except (TimeoutError, RPCError):
                await self.sleep(RETRY)
        return None

    async def renew(self, job: int) -> None:
        """Stage 1: every LEASE / 3 seconds, rpc {"type": "renew", "job": job} to LOCK, forever.
        Let an RPCError or TimeoutError end the loop: the lease is gone."""
        raise NotImplementedError("TODO stage 1: Worker.renew")


class Storage(Node):
    """Holds the shared report.

    Contract:
      - `write` {job, part, data, token} -> {"type": "write_ok"}, or {"type": "error",
        "code": 22} when the write is refused (stage 2).
    """

    def __init__(self, node_id: str, node_ids: list[str]) -> None:
        super().__init__(node_id, node_ids)
        self.report: dict[int, str] = {}  # part -> its text
        # Stage 2: self.highest = 0, the newest token seen.

    def is_stale(self, token) -> bool:
        """Stage 2: True when a write comes from a lost lock: no token, or a token older
        (smaller) than self.highest. An equal token is the same holder's next part."""
        raise NotImplementedError("TODO stage 2: Storage.is_stale")

    async def on_write(self, msg: Message) -> None:
        # Stage 2: if self.is_stale(token), reply {"type": "error", "code": 22} and stop;
        # otherwise remember self.highest = token, then write.
        self.report[msg.body["part"]] = msg.body["data"]
        self.reply(msg, {"type": "write_ok"})

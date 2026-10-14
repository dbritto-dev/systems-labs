"""Run lab code in a child process, so a bug or an endless loop never freezes the viewer.

`Job("labs.caching.scenario:run", "main", {"chunk": 0, "seed": 1})` calls
`run("main", chunk=0, seed=1)` in a fresh process (spawn). `poll()` returns
None while it runs, then ("ok", data) or ("error", message).
"""

from __future__ import annotations

import importlib
import sys
import multiprocessing as mp
import time
import traceback
from pathlib import Path
from typing import Any

from core.contract import module_path
from core.i18n import screen_text

TIMEOUT = 20.0
ROOT = Path(__file__).resolve().parent.parent


def _call(target: str, variant: str, params: dict) -> Any:
    module, _, func = target.partition(":")
    return getattr(importlib.import_module(module), func)(variant, **params)


def _yours(filename: str) -> bool:
    """A frame in lab code you edit (not the scenario, the tool, or Python itself)."""
    path = str(Path(filename).resolve())
    if path.endswith("scenario.py") or path.startswith((str(ROOT / "core"), str(ROOT / "live"))):
        return False
    return not path.startswith((sys.base_prefix, sys.prefix)) and "site-packages" not in path


def describe(exc: BaseException, default: str = "") -> str:
    """One short message: what went wrong and which file to edit."""
    where = ""
    tb = traceback.extract_tb(exc.__traceback__)
    if isinstance(exc, SyntaxError) and exc.filename:
        where = f"{_rel(exc.filename)}:{exc.lineno}"
    elif isinstance(exc, ImportError) and getattr(exc, "path", None):
        where = _rel(exc.path)
    else:
        mine = [f for f in tb if _yours(f.filename)]
        if mine:
            where = f"{_rel(mine[-1].filename)}:{mine[-1].lineno}"
    where = where or default
    msg = f"{type(exc).__name__}: {exc}"
    return f"{msg}  ({screen_text().EDIT_HERE.format(where=where)})" if where else msg


def _rel(path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return path


def _child(conn, target: str, variant: str, params: dict) -> None:
    try:
        result = ("ok", _call(target, variant, params))
    except BaseException as exc:  # noqa: BLE001 - report everything to the parent
        lab = target.split(".")[1] if target.startswith("labs.") else ""
        default = _rel(str(variant)) if str(variant).endswith(".py") else (
            _rel(str(module_path(lab, variant))) if lab else "")
        result = ("error", describe(exc, default))
    try:
        conn.send(result)
    finally:
        conn.close()


class Job:
    def __init__(self, target: str, variant: str, params: dict | None = None,
                 timeout: float = TIMEOUT) -> None:
        self.target = target
        self.variant = variant
        self.params = dict(params or {})
        self.timeout = timeout
        self.result: tuple[str, Any] | None = None
        ctx = mp.get_context("spawn")
        self._recv, send = ctx.Pipe(duplex=False)
        self._proc = ctx.Process(target=_child, args=(send, target, variant, self.params), daemon=True)
        self._started = time.monotonic()
        self._proc.start()
        send.close()

    def poll(self) -> tuple[str, Any] | None:
        if self.result is not None:
            return self.result
        try:
            if self._recv.poll():
                self.result = self._recv.recv()
                self._proc.join(timeout=1)
                return self.result
        except (EOFError, OSError):
            self.result = ("error", screen_text().RUN_CRASHED.format(code=self._proc.exitcode))
            return self.result
        if not self._proc.is_alive():
            self._proc.join()
            self.result = ("error", screen_text().RUN_CRASHED.format(code=self._proc.exitcode))
            return self.result
        if time.monotonic() - self._started > self.timeout:
            self.cancel()
            self.result = ("error", screen_text().NO_RESULT.format(seconds=f"{self.timeout:.0f}"))
            return self.result
        return None

    def cancel(self) -> None:
        if self._proc.is_alive():
            self._proc.kill()
            self._proc.join(timeout=2)
        self._recv.close()

    def run_sync(self) -> tuple[str, Any]:
        while True:
            r = self.poll()
            if r is not None:
                return r
            try:
                self._recv.poll(0.05)
            except (EOFError, OSError):
                pass


def _stream_child(conn, target: str, variant: str, params: dict) -> None:
    """Run one endless simulation; send the next piece each time the parent asks."""
    lab = target.split(".")[1] if target.startswith("labs.") else ""
    default = _rel(str(variant)) if str(variant).endswith(".py") else (
        _rel(str(module_path(lab, variant))) if lab else "")
    try:
        module, _, func = target.partition(":")
        mod = importlib.import_module(module)
        names = getattr(mod, "NAMES", None)
        if lab and names and isinstance(variant, str):
            from core.contract import load

            load(lab, variant, names)  # your code imports and has every name: say so before simulating
        conn.send(("progress", "loaded"))
        pieces = getattr(mod, func)(variant, **params)
        while conn.recv() == "next":
            conn.send(("ok", next(pieces)))
    except (EOFError, KeyboardInterrupt):
        pass
    except BaseException as exc:  # noqa: BLE001 - report everything to the parent
        try:
            conn.send(("error", describe(exc, default)))
        except OSError:
            pass
    finally:
        conn.close()


class StreamJob:
    """A child process running one endless simulation.

    `request()` asks for the next piece; `poll()` returns None while it is being
    simulated, then ("ok", piece) or ("error", message). Each piece gets
    `timeout` seconds. The simulation keeps its state between pieces.
    """

    def __init__(self, target: str, variant: str, params: dict | None = None,
                 timeout: float = TIMEOUT) -> None:
        self.timeout = timeout
        ctx = mp.get_context("spawn")
        self._conn, child = ctx.Pipe(duplex=True)
        self._proc = ctx.Process(target=_stream_child, args=(child, target, variant, dict(params or {})),
                                 daemon=True)
        self._proc.start()
        child.close()
        self._asked: float | None = None
        self.dead = False
        self.started = time.monotonic()
        self.progress = "starting"  # then "loaded" (your code imported), then pieces arrive

    @property
    def waiting(self) -> bool:
        return self._asked is not None

    def request(self) -> None:
        if self._asked is None and not self.dead:
            self._conn.send("next")
            self._asked = time.monotonic()

    def poll(self) -> tuple[str, Any] | None:
        if self._asked is None:
            return None
        try:
            while self._conn.poll():
                result = self._conn.recv()
                if result[0] == "progress":
                    self.progress = result[1]
                    continue
                self._asked = None
                self.progress = "running"
                if result[0] == "error":
                    self.cancel()
                return result
        except (EOFError, OSError):
            return self._dead(screen_text().RUN_CRASHED.format(code=self._proc.exitcode))
        if not self._proc.is_alive():
            return self._dead(screen_text().RUN_CRASHED.format(code=self._proc.exitcode))
        if time.monotonic() - self._asked > self.timeout:
            return self._dead(screen_text().NO_RESULT.format(seconds=f"{self.timeout:.0f}"))
        return None

    def _dead(self, message: str) -> tuple[str, str]:
        self._asked = None
        self.cancel()
        return ("error", message)

    def cancel(self) -> None:
        self.dead = True
        if self._proc.is_alive():
            self._proc.kill()
            self._proc.join(timeout=2)
        self._conn.close()

    def next_sync(self) -> tuple[str, Any]:
        self.request()
        while True:
            r = self.poll()
            if r is not None:
                return r
            try:
                self._conn.poll(0.05)
            except (EOFError, OSError):
                pass


AHEAD = 40.0  # ask for the next minute when the playhead is this close to the end


class Feed:
    """Keeps a World's run for one variant growing, a minute at a time, forever.

    One child process per run simulates it without ever restarting.
    `restart()` begins a new run (a new generation). The old run stays on
    screen until the first minute of the new one arrives. Pieces from a
    replaced run are ignored.
    """

    def __init__(self, world, lab: str, variant: str, seed: int = 1, timeout: float = TIMEOUT) -> None:
        self.world = world
        self.lab = lab
        self.variant = variant
        self.seed = seed
        self.timeout = timeout
        self.gen = 0
        self.job: StreamJob | None = None
        self.error: str | None = None
        self.restarted = False  # set when the first minute of a new run arrived
        self._got = 0  # pieces received from the current job

    @property
    def target(self) -> str:
        return f"labs.{self.lab}.scenario:stream"

    @property
    def run(self):
        r = self.world.runs.get(self.variant)
        return r if r is not None and r.gen == self.gen else None

    @property
    def busy(self) -> bool:
        return self.job is not None and self.job.waiting

    @property
    def loading(self) -> tuple[str, float] | None:
        """(step, seconds so far) while the first minute of a run is on its way, else None."""
        if self.job is None or self._got or self.error is not None:
            return None
        return self.job.progress, time.monotonic() - self.job.started

    def restart(self) -> None:
        if self.job is not None:
            self.job.cancel()
        self.gen += 1
        self.error = None
        self._got = 0
        params = dict(self.world.params, seed=self.seed)
        self.job = StreamJob(self.target, self.variant, params, timeout=self.timeout)
        self.job.request()

    def _collect(self) -> None:
        r = self.job.poll() if self.job is not None else None
        if r is None:
            return
        status, data = r
        if status == "error":
            self.error = data
            return
        self.error = None
        if self._got == 0:
            self.world.start(self.variant, self.gen)
            self.restarted = True
        self._got += 1
        self.world.append(self.variant, data)

    def tick(self, t: float) -> None:
        """Collect a finished minute, and ask for the next one when needed."""
        self._collect()
        run = self.run
        if (self.job is not None and not self.job.waiting and self.error is None
                and run is not None and run.end - t < AHEAD):
            self.job.request()

    def build_until(self, t: float) -> None:
        """Synchronously simulate up to time t (for --at and tests)."""
        self.restart()
        while self.job is not None and self.job.waiting:
            while self.job.waiting:
                self._collect()
                if self.error is not None:
                    return
                time.sleep(0.01)
            run = self.run
            if run is None or run.end >= t + AHEAD:
                return
            self.job.request()

    def close(self) -> None:
        if self.job is not None:
            self.job.cancel()

"""Run a program in a pseudo-terminal, for the tests that check the real viewer.

It uses `pty.openpty()` and `subprocess.Popen` rather than `pty.fork()`, which is not safe in a process with
threads (pytest-xdist workers have them). The output is drained the whole time, so the program never blocks
writing its frames, and a program that will not exit is killed rather than hanging the test run.
"""

from __future__ import annotations

import fcntl
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time


def run_in_pty(args: list[str], keys: bytes = b"", ready: tuple[bytes, ...] = (), seconds: float = 20.0,
               size: tuple[int, int] = (110, 44)) -> tuple[int | None, str]:
    """Run `python <args>` in a pty of `size` (cols, rows); type `keys` once any of `ready` shows up (at once
    without `ready`); return (exit code, or None if it had to be killed; everything it wrote)."""
    master, slave = pty.openpty()
    cols, rows = size
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    env = dict(os.environ, COLUMNS=str(cols), LINES=str(rows))
    proc = subprocess.Popen([sys.executable, *args], stdin=slave, stdout=slave, stderr=slave, env=env,
                            start_new_session=True, close_fds=True)
    os.close(slave)
    out, typed = b"", not keys
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            r, _, _ = select.select([master], [], [], 0.1)
            if r:
                try:
                    out += os.read(master, 65536)
                except OSError:
                    pass
            if not typed and (not ready or any(word in out for word in ready)):
                os.write(master, keys)
                typed = True
            if proc.poll() is not None:
                while True:  # what is still in the pipe
                    r, _, _ = select.select([master], [], [], 0.05)
                    if not r:
                        break
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    out += chunk
                return proc.returncode, out.decode("utf-8", "replace")
        proc.kill()
        proc.wait()
        return None, out.decode("utf-8", "replace")
    finally:
        os.close(master)

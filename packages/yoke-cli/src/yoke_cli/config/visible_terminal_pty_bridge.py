"""Bridge a visible operator Terminal to a child PTY for TUI proofs.

Remote visual tests sometimes need a logged transcript while the child process
still sees a real terminal. Running the launcher under ``tee`` before creating
the child PTY turns stdout into a pipe, which hides the Terminal window size
from Textual. This bridge sizes the child PTY from stdout, then ``/dev/tty``,
then ``COLUMNS``/``LINES`` before forwarding bytes to stdout and a log file.
The child PTY is also re-synced after launch and before FIFO input is forwarded
so simple probes see the operator Terminal's current geometry. Textual TUIs
still need the visible Terminal window sized before launch so their first layout
starts at the final height.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import selectors
import signal
import struct
import subprocess
import sys
import termios
import time
from collections.abc import Sequence
from pathlib import Path


_DEFAULT_TERM = "xterm-256color"
_WINSIZE_FORMAT = "HHHH"
_WINSIZE_ZERO = b"\0" * struct.calcsize(_WINSIZE_FORMAT)
_WINSIZE_RESYNC_INTERVAL_SECONDS = 0.25


def _ioctl_winsize(fd: int) -> bytes | None:
    try:
        return fcntl.ioctl(fd, termios.TIOCGWINSZ, _WINSIZE_ZERO)
    except OSError:
        return None


def _env_winsize(environ: dict[str, str] | None = None) -> bytes | None:
    environ = environ if environ is not None else os.environ
    try:
        columns = int(environ.get("COLUMNS", ""))
        lines = int(environ.get("LINES", ""))
    except ValueError:
        return None
    if columns <= 0 or lines <= 0:
        return None
    return struct.pack(_WINSIZE_FORMAT, lines, columns, 0, 0)


def read_terminal_winsize(
    *,
    stdout_fd: int | None = None,
    environ: dict[str, str] | None = None,
    tty_path: str = "/dev/tty",
) -> bytes | None:
    """Return the best available terminal size as a packed winsize struct."""

    if stdout_fd is None:
        stdout_fd = sys.stdout.fileno()

    if os.isatty(stdout_fd):
        winsize = _ioctl_winsize(stdout_fd)
        if winsize is not None:
            return winsize

    tty_fd: int | None = None
    try:
        tty_fd = os.open(tty_path, os.O_RDONLY | os.O_NOCTTY)
        winsize = _ioctl_winsize(tty_fd)
        if winsize is not None:
            return winsize
    except OSError:
        pass
    finally:
        if tty_fd is not None:
            try:
                os.close(tty_fd)
            except OSError:
                pass

    return _env_winsize(environ)


def apply_winsize(fd: int, winsize: bytes | None) -> None:
    if winsize is None:
        return
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        pass


def _resync_child_winsize(
    master_fd: int,
    proc: subprocess.Popen[bytes] | None,
    *,
    previous: bytes | None,
    environ: dict[str, str],
    tty_path: str,
) -> bytes | None:
    current = read_terminal_winsize(environ=environ, tty_path=tty_path)
    if current is None or current == previous:
        return previous
    apply_winsize(master_fd, current)
    if proc is not None and proc.poll() is None:
        try:
            os.kill(proc.pid, signal.SIGWINCH)
        except OSError:
            pass
    return current


def _open_fifo(path: str) -> int:
    try:
        os.mkfifo(path, 0o600)
    except FileExistsError:
        pass
    return os.open(path, os.O_RDONLY | os.O_NONBLOCK)


def _read_pty(master_fd: int) -> bytes | None:
    try:
        data = os.read(master_fd, 65536)
    except BlockingIOError:
        return b""
    except OSError:
        return None
    return data if data else None


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def run_bridge(
    cmd: Sequence[str],
    *,
    fifo_path: str,
    log_path: str,
    status_path: str,
    environ: dict[str, str] | None = None,
    tty_path: str = "/dev/tty",
) -> int:
    if not cmd:
        raise ValueError("missing command")

    env = dict(environ or os.environ)
    env.setdefault("TERM", _DEFAULT_TERM)

    master_fd, slave_fd = os.openpty()
    resize_fd: int | None = os.dup(slave_fd)
    winsize = read_terminal_winsize(environ=env, tty_path=tty_path)
    if resize_fd is not None:
        apply_winsize(resize_fd, winsize)
    last_winsize_check = 0.0

    proc: subprocess.Popen[bytes] | None = None

    def close_resize_fd() -> None:
        nonlocal resize_fd
        if resize_fd is None:
            return
        try:
            os.close(resize_fd)
        except OSError:
            pass
        resize_fd = None

    def handle_winch(_signum: int, _frame: object) -> None:
        nonlocal winsize, last_winsize_check
        last_winsize_check = time.monotonic()
        if resize_fd is None:
            return
        winsize = _resync_child_winsize(
            resize_fd,
            proc,
            previous=winsize,
            environ=env,
            tty_path=tty_path,
        )

    try:
        proc = subprocess.Popen(
            list(cmd),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env=env,
        )
    finally:
        os.close(slave_fd)

    old_winch = signal.getsignal(signal.SIGWINCH)
    signal.signal(signal.SIGWINCH, handle_winch)
    handle_winch(signal.SIGWINCH, None)

    fifo_fd = _open_fifo(fifo_path)
    selector = selectors.DefaultSelector()
    selector.register(master_fd, selectors.EVENT_READ, "pty")
    selector.register(fifo_fd, selectors.EVENT_READ, "fifo")
    pty_registered = True
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    Path(status_path).parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab", buffering=0)
    with open(status_path, "w", encoding="utf-8") as status:
        status.write(f"pid={proc.pid}\nfifo={fifo_path}\nlog={log_path}\n")

    try:
        while pty_registered:
            child_done = proc.poll() is not None
            if child_done:
                close_resize_fd()
            now = time.monotonic()
            if now - last_winsize_check >= _WINSIZE_RESYNC_INTERVAL_SECONDS:
                handle_winch(signal.SIGWINCH, None)
            events = selector.select(timeout=0 if child_done else 0.1)
            if not events and child_done:
                data = _read_pty(master_fd)
                if data:
                    _write_all(sys.stdout.fileno(), data)
                    log.write(data)
                    continue
                selector.unregister(master_fd)
                pty_registered = False
                break

            for key, _mask in events:
                if key.data == "pty":
                    data = _read_pty(master_fd)
                    if data is None:
                        selector.unregister(master_fd)
                        pty_registered = False
                        break
                    if data:
                        _write_all(sys.stdout.fileno(), data)
                        log.write(data)
                else:
                    try:
                        data = os.read(fifo_fd, 4096)
                    except BlockingIOError:
                        data = b""
                    if data:
                        handle_winch(signal.SIGWINCH, None)
                        _write_all(master_fd, data)
                    else:
                        selector.unregister(fifo_fd)
                        os.close(fifo_fd)
                        time.sleep(0.05)
                        fifo_fd = _open_fifo(fifo_path)
                        selector.register(fifo_fd, selectors.EVENT_READ, "fifo")
        return int(proc.wait())
    finally:
        signal.signal(signal.SIGWINCH, old_winch)
        try:
            selector.close()
        except Exception:
            pass
        try:
            log.close()
        except Exception:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        close_resize_fd()
        try:
            os.close(fifo_fd)
        except OSError:
            pass
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a command in a logged child PTY sized from the visible "
            "Terminal, even when the launcher logs through a pipe."
        )
    )
    parser.add_argument("--fifo", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cmd = list(args.cmd)
    if cmd[:1] == ["--"]:
        cmd = cmd[1:]
    if not cmd:
        raise SystemExit("missing command")
    return run_bridge(cmd, fifo_path=args.fifo, log_path=args.log, status_path=args.status)


if __name__ == "__main__":
    raise SystemExit(main())

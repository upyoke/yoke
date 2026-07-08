from __future__ import annotations

import os
import signal
import struct
import sys

from yoke_cli.config import visible_terminal_pty_bridge as bridge


def _unpack_winsize(payload: bytes) -> tuple[int, int]:
    lines, columns, _xpixels, _ypixels = struct.unpack("HHHH", payload)
    return lines, columns


def _pack_winsize(lines: int, columns: int) -> bytes:
    return struct.pack("HHHH", lines, columns, 0, 0)


def test_read_terminal_winsize_falls_back_to_env_when_outer_stdout_is_pipe(tmp_path):
    missing_tty = tmp_path / "missing-tty"
    read_fd, write_fd = os.pipe()
    try:
        winsize = bridge.read_terminal_winsize(
            stdout_fd=write_fd,
            environ={"LINES": "37", "COLUMNS": "123"},
            tty_path=str(missing_tty),
        )
    finally:
        os.close(read_fd)
        os.close(write_fd)

    assert winsize is not None
    assert _unpack_winsize(winsize) == (37, 123)


def test_run_bridge_sizes_child_pty_from_env_when_outer_stdout_is_pipe(tmp_path, capfd):
    log_path = tmp_path / "bridge.log"
    status_path = tmp_path / "bridge.status"
    fifo_path = tmp_path / "bridge.fifo"
    missing_tty = tmp_path / "missing-tty"
    code = (
        "import os; "
        "size = os.get_terminal_size(); "
        "print(f'CHILD_SIZE={size.columns}x{size.lines}', flush=True)"
    )

    rc = bridge.run_bridge(
        [sys.executable, "-c", code],
        fifo_path=str(fifo_path),
        log_path=str(log_path),
        status_path=str(status_path),
        environ={**os.environ, "COLUMNS": "123", "LINES": "37"},
        tty_path=str(missing_tty),
    )

    assert rc == 0
    stdout = capfd.readouterr().out
    log = log_path.read_text(encoding="utf-8")
    status = status_path.read_text(encoding="utf-8")
    assert "CHILD_SIZE=123x37" in stdout
    assert "CHILD_SIZE=123x37" in log
    assert f"fifo={fifo_path}" in status
    assert f"log={log_path}" in status


def test_resync_child_winsize_updates_pty_and_signals_child(monkeypatch):
    initial = _pack_winsize(30, 120)
    resized = _pack_winsize(58, 211)
    applied: list[tuple[int, bytes]] = []
    signaled: list[tuple[int, int]] = []

    class Proc:
        pid = 12345

        def poll(self):
            return None

    monkeypatch.setattr(
        bridge,
        "read_terminal_winsize",
        lambda **_kwargs: resized,
    )
    monkeypatch.setattr(
        bridge,
        "apply_winsize",
        lambda fd, winsize: applied.append((fd, winsize)),
    )
    monkeypatch.setattr(
        bridge.os,
        "kill",
        lambda pid, sig: signaled.append((pid, sig)),
    )

    result = bridge._resync_child_winsize(
        7,
        Proc(),
        previous=initial,
        environ={},
        tty_path="/dev/tty",
    )

    assert result == resized
    assert applied == [(7, resized)]
    assert signaled == [(12345, signal.SIGWINCH)]


def test_run_bridge_resyncs_child_pty_after_outer_terminal_resize(
    tmp_path,
    monkeypatch,
    capfd,
):
    log_path = tmp_path / "bridge.log"
    status_path = tmp_path / "bridge.status"
    fifo_path = tmp_path / "bridge.fifo"
    initial = _pack_winsize(30, 120)
    resized = _pack_winsize(58, 211)
    read_count = {"value": 0}
    applied: list[bytes] = []
    signaled: list[tuple[int, int]] = []

    def fake_read_terminal_winsize(**_kwargs):
        read_count["value"] += 1
        return initial if read_count["value"] == 1 else resized

    monkeypatch.setattr(bridge, "_WINSIZE_RESYNC_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(
        bridge,
        "read_terminal_winsize",
        fake_read_terminal_winsize,
    )
    monkeypatch.setattr(
        bridge,
        "apply_winsize",
        lambda _fd, winsize: applied.append(winsize),
    )
    monkeypatch.setattr(
        bridge.os,
        "kill",
        lambda pid, sig: signaled.append((pid, sig)),
    )
    code = "import time; time.sleep(0.1); print('DONE', flush=True)"

    rc = bridge.run_bridge(
        [sys.executable, "-c", code],
        fifo_path=str(fifo_path),
        log_path=str(log_path),
        status_path=str(status_path),
        environ=os.environ,
        tty_path="/dev/tty",
    )

    assert rc == 0
    assert resized in applied
    assert any(sig == signal.SIGWINCH for _pid, sig in signaled)
    assert "DONE" in capfd.readouterr().out

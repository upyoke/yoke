from __future__ import annotations

import os
import struct
import sys

from yoke_cli.config import visible_terminal_pty_bridge as bridge


def _unpack_winsize(payload: bytes) -> tuple[int, int]:
    lines, columns, _xpixels, _ypixels = struct.unpack("HHHH", payload)
    return lines, columns


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

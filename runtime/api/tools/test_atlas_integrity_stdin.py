"""The Atlas integrity audit never reads the caller's real stdin.

The audit runs skill recipes and help pages through the in-process CLI.
A recipe that passes ``--stdin`` must read an empty buffer, not block on
an open pipe the caller never closes.
"""

from __future__ import annotations

import io
import os
import sys
import threading
from pathlib import Path

from yoke_core.tools import atlas_integrity_audit as aia

_TIMEOUT_SECONDS = 60


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "runtime" / "api" / "tools").is_dir():
            return parent
    raise RuntimeError("could not infer repo root from test file path")


def _build_report_with_stdin(monkeypatch, stdin) -> dict | None:
    monkeypatch.setattr(sys, "stdin", stdin)
    result: dict = {}

    def _run() -> None:
        result["report"] = aia.build_report(
            _repo_root(), generated_at="1970-01-01T00:00:00Z"
        )

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(_TIMEOUT_SECONDS)
    return result.get("report")


def test_open_stdin_pipe_matches_empty_stdin(monkeypatch) -> None:
    read_fd, write_fd = os.pipe()
    pipe_stdin = os.fdopen(read_fd, "r")
    try:
        piped = _build_report_with_stdin(monkeypatch, pipe_stdin)
    finally:
        os.close(write_fd)
        pipe_stdin.close()
    assert piped is not None, "build_report blocked on an open stdin pipe"

    empty = _build_report_with_stdin(monkeypatch, io.StringIO(""))
    assert empty is not None
    assert piped["recipes"] == empty["recipes"]
    assert piped["help_pages"] == empty["help_pages"]

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


def _build_report_with_stdin(monkeypatch, stdin, repo_root) -> dict | None:
    monkeypatch.setattr(sys, "stdin", stdin)
    result: dict = {}

    def _run() -> None:
        result["report"] = aia.build_report(
            repo_root, generated_at="1970-01-01T00:00:00Z"
        )

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(_TIMEOUT_SECONDS)
    return result.get("report")


def test_open_stdin_pipe_matches_empty_stdin(monkeypatch, tmp_path: Path) -> None:
    skill = tmp_path / ".agents/skills/yoke/stdin.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "```sh\nyoke feedback --to universe --category observation --stdin\n```\n"
    )
    # Keep real help rendering on one command, rather than the entire CLI tree.
    registry = aia.collect_subcommand_registry()
    registry["rows"] = [
        row for row in registry["rows"] if row["cli_tokens"] == ["feedback"]
    ]
    registry["count"] = len(registry["rows"])
    assert registry["count"] == 1
    monkeypatch.setattr(aia, "collect_subcommand_registry", lambda: registry)
    read_fd, write_fd = os.pipe()
    pipe_stdin = os.fdopen(read_fd, "r")
    try:
        piped = _build_report_with_stdin(monkeypatch, pipe_stdin, tmp_path)
    finally:
        os.close(write_fd)
        pipe_stdin.close()
    assert piped is not None, "build_report blocked on an open stdin pipe"

    empty = _build_report_with_stdin(monkeypatch, io.StringIO(""), tmp_path)
    assert empty is not None
    assert piped["recipes"]["total"] == 1
    # Empty evidence is refused after stdin is isolated, without blocking.
    assert piped["recipes"]["failed"] == 1
    assert piped["recipes"]["verdicts"][0]["error"] == "cli_main exit=2"
    assert piped["recipes"] == empty["recipes"]
    assert piped["help_pages"] == empty["help_pages"]

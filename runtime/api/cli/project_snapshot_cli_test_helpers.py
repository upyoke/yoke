"""Shared fixtures for project snapshot CLI tests."""

from __future__ import annotations

import io
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallResponse

CALLS: List[Dict[str, Any]] = []
OVERSIZED_HTTPS_PAYLOAD_BYTES = 900_001


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("import json\n")
    (repo / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    return repo


def head_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def run_cli(
    *argv: str,
    response: FunctionCallResponse | None = None,
    responses: List[FunctionCallResponse] | None = None,
):
    CALLS.clear()
    queued = list(responses or [])

    def fake_call_dispatcher(**kwargs):
        CALLS.append(kwargs)
        if queued:
            return queued.pop(0)
        return response or FunctionCallResponse(
            success=True,
            function=kwargs["function_id"],
            version="v1",
            result={
                "snapshots": [
                    {
                        "status": "created",
                        "ref": "HEAD",
                        "commit_sha": "abc",
                        "snapshot_id": 1,
                    }
                ],
                "warnings": [],
            },
        )

    out = io.StringIO()
    err = io.StringIO()
    with patch(
        "yoke_cli.commands.adapters.project_snapshot.call_dispatcher",
        side_effect=fake_call_dispatcher,
    ), patch(
        "yoke_cli.commands.adapters.project_snapshot_chunked.call_dispatcher",
        side_effect=fake_call_dispatcher,
    ), patch(
        "yoke_cli.commands.adapters.project_snapshot.ensure_handlers_loaded"
    ), patch(
        "yoke_cli.commands.adapters.project_snapshot_chunked.ensure_handlers_loaded"
    ):
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_main(list(argv))
    return rc, out.getvalue(), err.getvalue()

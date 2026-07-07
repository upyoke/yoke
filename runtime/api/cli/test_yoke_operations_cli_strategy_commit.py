"""Tests for ``yoke strategy ingest --commit`` (one-shot write-back + commit).

Sibling of :mod:`test_yoke_operations_cli_strategy` (kept separate so that
file stays under the authored-line cap). Covers the ergonomic flag that
collapses edit -> ingest -> render -> commit into one atomic, correctly
ordered step (the friction this slice removes).
"""

from __future__ import annotations

import io
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import List
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _ingest_stub(docs):
    def _stub(request: FunctionCallRequest) -> FunctionCallResponse:
        return FunctionCallResponse(
            success=True, function=request.function, version=request.version,
            request_id=request.request_id,
            result={"project_id": 1, "project_slug": "yoke", "docs": docs},
        )

    return _stub


def _run_ingest(argv, docs, tmp_path: Path):
    """Run `yoke strategy ingest ...` with dispatch + git mocked.

    Returns ``(rc, [git argv lists])``. ``read_ingest_files`` is mocked so
    no on-disk source file is required; ``subprocess.run`` is captured so no
    real git runs. NOTE: patching ``module.subprocess.run`` patches the
    shared ``subprocess`` module, so the capture also sees the ``git
    rev-parse`` calls target-root resolution / workspace-authority make —
    use :func:`_staging` to isolate the add/commit calls under test.
    """
    git_calls: List[List[str]] = []

    def _fake_run(cmd, **kwargs):
        git_calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    env = {"YOKE_SESSION_ID": "test-session"}
    with patch.dict("os.environ", env), patch(
        "yoke_core.domain.yoke_function_dispatch.dispatch",
        side_effect=_ingest_stub(docs),
    ), patch(
        "yoke_cli.commands._helpers.ensure_handlers_loaded"
    ), patch(
        "yoke_cli.commands.adapters.strategy_render.read_ingest_files",
        return_value=[{"slug": "MISSION", "file_text": "x"}],
    ), patch(
        "yoke_cli.commands.adapters.strategy_commit.subprocess.run",
        side_effect=_fake_run,
    ):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli_main(
                ["strategy", "ingest", *argv, "--target-root", str(tmp_path)]
            )
    return rc, git_calls


def _staging(git_calls: List[List[str]]) -> List[List[str]]:
    """The add/commit calls only — drops rev-parse/--git-common-dir noise."""
    return [c for c in git_calls if len(c) > 3 and c[3] in ("add", "commit")]


_WRITTEN_DOC = {
    "slug": "MISSION", "status": "written", "updated_at": "y",
    "old_lines": 1, "new_lines": 2, "line_delta": 1,
    "file_text": "<!-- h -->\n# MISSION\n",
}
_UNCHANGED_DOC = {
    "slug": "MISSION", "status": "unchanged", "updated_at": "y",
    "old_lines": 2, "new_lines": 2, "line_delta": 0,
}


class TestStrategyIngestCommit:
    def test_commit_stages_and_commits_written_views(self, tmp_path: Path):
        rc, git_calls = _run_ingest(
            ["MISSION", "--commit", "strategy: edit MISSION"],
            [_WRITTEN_DOC], tmp_path,
        )
        assert rc == 0
        # Exactly two staging invocations: add the view path, then commit -m MSG.
        staging = _staging(git_calls)
        assert len(staging) == 2
        add, commit = staging
        view = str(tmp_path / ".yoke" / "strategy" / "MISSION.md")
        assert add[:3] == ["git", "-C", str(tmp_path)]
        assert add[3] == "add" and view in add
        assert commit[3:] == ["commit", "-m", "strategy: edit MISSION"]

    def test_commit_with_dry_run_is_usage_error(self, tmp_path: Path):
        rc, git_calls = _run_ingest(
            ["MISSION", "--commit", "msg", "--dry-run"], [_WRITTEN_DOC], tmp_path,
        )
        assert rc == 2
        assert git_calls == []  # rejected before any dispatch/git

    def test_commit_with_no_changed_docs_commits_nothing(self, tmp_path: Path):
        rc, git_calls = _run_ingest(
            ["MISSION", "--commit", "msg"], [_UNCHANGED_DOC], tmp_path,
        )
        assert rc == 0
        assert _staging(git_calls) == []  # nothing written -> nothing staged

    def test_no_commit_flag_never_touches_git(self, tmp_path: Path):
        rc, git_calls = _run_ingest(["MISSION"], [_WRITTEN_DOC], tmp_path)
        assert rc == 0
        assert _staging(git_calls) == []

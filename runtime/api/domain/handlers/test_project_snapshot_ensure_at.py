"""In-process integration coverage for ``project.snapshot.ensure_at``.

Proves the handler resolves the project, walks the requested commit's tree
server-side, and materializes a ``path_snapshots`` row — the local /
in-process leg of the ALL-MODES snapshot pre-warm. The relay leg is covered
by ``test_merge_worktree_post_transport``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from runtime.api.domain._path_snapshots_test_helpers import path_snapshot_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.project_snapshot_ensure_at import (
    ProjectSnapshotEnsureAtResponse,
    handle_project_snapshot_ensure_at,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hi\n")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")
    return repo, _git(repo, "rev-parse", "HEAD")


def _envelope(*, project=None, commit_sha=None, project_target=None):
    payload = {}
    if project is not None:
        payload["project"] = project
    if commit_sha is not None:
        payload["commit_sha"] = commit_sha
    return FunctionCallRequest(
        function="project.snapshot.ensure_at",
        actor=ActorContext(actor_id=None, session_id="s-snapshot-ensure"),
        target=TargetRef(kind="global", project_id=project_target),
        payload=payload,
    )


def test_ensure_at_builds_snapshot_for_head(tmp_path: Path):
    repo, sha = _make_repo(tmp_path)
    with path_snapshot_db(tmp_path, repo):  # repoints the DSN for the context
        outcome = handle_project_snapshot_ensure_at(
            _envelope(project="demo", commit_sha=sha)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["snapshot_id"] > 0
        assert outcome.result_payload["commit_sha"] == sha
        ProjectSnapshotEnsureAtResponse(**outcome.result_payload)


def test_ensure_at_is_idempotent(tmp_path: Path):
    repo, sha = _make_repo(tmp_path)
    with path_snapshot_db(tmp_path, repo):
        first = handle_project_snapshot_ensure_at(
            _envelope(project="demo", commit_sha=sha)
        )
        second = handle_project_snapshot_ensure_at(
            _envelope(project="demo", commit_sha=sha)
        )
        assert first.primary_success and second.primary_success
        assert (
            first.result_payload["snapshot_id"]
            == second.result_payload["snapshot_id"]
        )


def test_ensure_at_missing_commit_sha_is_payload_invalid(tmp_path: Path):
    outcome = handle_project_snapshot_ensure_at(_envelope(project="demo"))
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"


def test_ensure_at_missing_project_is_rejected(tmp_path: Path):
    outcome = handle_project_snapshot_ensure_at(_envelope(commit_sha="deadbeef"))
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "project_required"

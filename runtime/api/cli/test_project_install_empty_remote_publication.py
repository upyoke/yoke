"""An empty remote is the first push, never an unreadable remote."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import repo_upstream_git
from yoke_cli.config.credentialed_git_attribution import (
    CredentialDecision,
    attributed,
)
from yoke_cli.project_install import publication_outcome
from yoke_cli.project_install import publication_reconcile
from yoke_cli.project_install import runner

from runtime.api.cli.project_install_publication_test_support import (
    bind_bundle,
    git,
    identify,
)


@pytest.fixture(autouse=True)
def _isolated_machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


def _empty_remote_clone(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True,
    )
    checkout = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(checkout)],
        check=True,
        capture_output=True,
    )
    identify(checkout)
    return remote, checkout


def _attributed_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Append the credential line a real credentialed fetch carries."""
    real_fetch = repo_upstream_git.fetch_branch
    decision = CredentialDecision(
        network=True, url="https://github.com/demo/demo", token_applied=True,
    )

    def fetch(*args, **kwargs):
        result = real_fetch(*args, **kwargs)
        return result if result.returncode == 0 else attributed(result, decision)

    monkeypatch.setattr(repo_upstream_git, "fetch_branch", fetch)


def test_attributed_missing_branch_reads_as_missing_not_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _remote, checkout = _empty_remote_clone(tmp_path)
    git(checkout, "commit", "-q", "--allow-empty", "-m", "first")
    _attributed_fetch(monkeypatch)

    state = publication_reconcile.read_remote_state(checkout, branch="main")

    assert state.status == publication_reconcile.REMOTE_BRANCH_MISSING
    assert "couldn't find remote ref" in state.detail.lower()
    assert [commit.subject for commit in state.local_only] == ["first"]


def test_install_into_an_empty_remote_ends_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, checkout = _empty_remote_clone(tmp_path)
    bind_bundle(monkeypatch)
    _attributed_fetch(monkeypatch)

    report = runner.install(checkout, project_id=7)

    publication = report["publication"]
    assert publication["status"] == publication_outcome.PUBLISHED
    assert publication["commit"] == report["commit"]["sha"]
    assert git(remote, "rev-parse", "main").stdout.strip() == report["commit"]["sha"]


def test_operator_commits_are_not_published_into_an_empty_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, checkout = _empty_remote_clone(tmp_path)
    (checkout / "app.py").write_text("print('mine')\n", encoding="utf-8")
    git(checkout, "add", "-A")
    git(checkout, "commit", "-q", "-m", "operator work")
    bind_bundle(monkeypatch)

    report = runner.install(checkout, project_id=7)

    publication = report["publication"]
    assert publication["status"] == publication_outcome.PENDING
    assert "operator work" in publication["detail"]
    assert not git(remote, "for-each-ref", "refs/heads").stdout.strip()


def test_snapshot_sync_runs_after_the_first_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _remote, checkout = _empty_remote_clone(tmp_path)
    bind_bundle(monkeypatch)
    heads: list[str] = []

    def record_head(**_kwargs):
        heads.append(git(checkout, "rev-parse", "--verify", "HEAD").stdout.strip())
        return {"attempted": True, "status": "ok", "message": "", "repair_command": ""}

    monkeypatch.setattr(runner, "sync_local_snapshot_for_write", record_head)

    report = runner.install(checkout, project_id=7)

    assert heads == [report["commit"]["sha"]]
    assert report["snapshot_sync"]["status"] == "ok"


def test_deferred_publication_names_setup_as_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _remote, checkout = _empty_remote_clone(tmp_path)
    bind_bundle(monkeypatch)

    report = runner.install(
        checkout,
        project_id=7,
        publish_skip_reason=publication_outcome.DEFERRED_REASON,
    )

    assert report["publication"] == {
        "status": publication_outcome.SKIPPED,
        "reason": "publication deferred to setup",
    }
    stderr = capsys.readouterr().err
    assert "skipped (publication deferred to setup)" in stderr
    assert "--no-publish" not in stderr

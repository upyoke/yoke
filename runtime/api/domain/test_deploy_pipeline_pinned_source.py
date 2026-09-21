"""Self-deploy driver source is frozen at the run's release_lineage."""

from __future__ import annotations

import io
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_cli.commands.deployment_execute import deployment_runs_execute
from yoke_core.domain import deploy_pipeline_pinned_source as pinned
from yoke_core.domain import deploy_pipeline_stage_receipt as receipt
from yoke_core.domain.deploy_pipeline_pinned_source import (
    DRIVER_SOURCE_DRIFT_PREFIX,
    DeployPinnedSourceError,
    EXIT_DRIVER_SOURCE_DRIFT,
    PINNED_RELEASE_ENV,
    PINNED_SOURCE_ROOT_ENV,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(root)],
        check=True,
    )
    _git(
        root,
        "-c",
        "user.name=pinned-source-test",
        "-c",
        "user.email=pinned-source-test@example.invalid",
        "commit",
        "--allow-empty",
        "-q",
        "-m",
        "base",
        "--no-gpg-sign",
    )
    return root


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=pinned-source-test",
        "-c",
        "user.email=pinned-source-test@example.invalid",
        "commit",
        "-q",
        "-m",
        name,
        "--no-gpg-sign",
    )
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _yoke_shape(repo: Path) -> None:
    marker = repo / "packages" / "yoke-core" / "src" / "yoke_core"
    marker.mkdir(parents=True)
    (marker / "__init__.py").write_text("", encoding="utf-8")


def test_https_prepare_takes_no_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pinned, "_https_transport", lambda: True)
    assert pinned.prepare_self_deploy_driver("run-1") is None


def test_non_yoke_checkout_is_not_this_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pinned, "_https_transport", lambda: False)
    monkeypatch.setattr(
        pinned.control_plane,
        "execution_context",
        lambda _run_id: {
            "run": {"release_lineage": "abc", "project": "other"},
        },
    )
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(pinned, "checkout_for_project_slug", lambda _p: other)
    assert pinned.prepare_self_deploy_driver("run-1") is None


def test_worktree_stays_at_the_pin_when_main_moves(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    pin = _commit(repo, "pin")
    later = _commit(repo, "later")
    assert later != pin
    path = pinned.ensure_pinned_worktree(str(repo), "run-20260921-010", pin)
    assert (path / "pin").read_text(encoding="utf-8") == "pin"
    assert not (path / "later").exists()
    assert (repo / "later").exists()
    head = subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    assert head == pin


def test_reuses_a_worktree_already_at_the_pin(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    pin = _commit(repo, "pin")
    first = pinned.ensure_pinned_worktree(str(repo), "run-1", pin)
    second = pinned.ensure_pinned_worktree(str(repo), "run-1", pin)
    assert first == second


def test_refuses_a_worktree_at_the_wrong_revision(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    pin = _commit(repo, "pin")
    later = _commit(repo, "later")
    pinned.ensure_pinned_worktree(str(repo), "run-1", pin)
    with pytest.raises(DeployPinnedSourceError, match="refuse rather than reset"):
        pinned.ensure_pinned_worktree(str(repo), "run-1", later)


def test_missing_commit_names_the_revision_and_redrive(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    missing = "ab" * 20
    with pytest.raises(DeployPinnedSourceError, match="not a commit") as err:
        pinned.ensure_pinned_worktree(str(repo), "run-1", missing)
    assert missing in str(err.value)
    assert "re-drive" in str(err.value)


def test_prepare_freezes_a_yoke_shaped_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _yoke_shape(repo)
    pin = _commit(repo, "pin")
    monkeypatch.setattr(pinned, "_https_transport", lambda: False)
    monkeypatch.setattr(
        pinned.control_plane,
        "execution_context",
        lambda _run_id: {
            "run": {"release_lineage": pin, "project": "yoke"},
        },
    )
    monkeypatch.setattr(pinned, "checkout_for_project_slug", lambda _p: repo)
    prepared = pinned.prepare_self_deploy_driver("run-20260921-010")
    assert prepared is not None
    assert prepared.lineage == pin
    assert prepared.root == pinned.driver_worktree_path(repo, "run-20260921-010")


def test_drift_refusal_is_silent_without_pin_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PINNED_RELEASE_ENV, raising=False)
    monkeypatch.delenv(PINNED_SOURCE_ROOT_ENV, raising=False)
    assert pinned.driver_source_drift_refusal("abc") is None


def test_matching_pin_is_not_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    pin = _commit(repo, "pin")
    monkeypatch.setenv(PINNED_RELEASE_ENV, pin)
    monkeypatch.setenv(PINNED_SOURCE_ROOT_ENV, str(repo))
    assert pinned.driver_source_drift_refusal(pin) is None


def test_drift_refusal_names_both_revisions_and_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    pin = _commit(repo, "pin")
    later = _commit(repo, "later")
    monkeypatch.setenv(PINNED_RELEASE_ENV, pin)
    monkeypatch.setenv(PINNED_SOURCE_ROOT_ENV, str(repo))
    msg = pinned.driver_source_drift_refusal(pin)
    assert msg is not None
    assert msg.startswith(DRIVER_SOURCE_DRIFT_PREFIX)
    assert later in msg
    assert pin in msg
    assert "SAME run id" in msg


def test_stage_dispatch_halts_on_drift_without_running_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        receipt,
        "driver_source_drift_refusal",
        lambda lineage: f"{DRIVER_SOURCE_DRIFT_PREFIX} {lineage}",
    )

    def _boom(*_args, **_kwargs):
        raise AssertionError("step runner must not run after drift")

    monkeypatch.setattr(receipt, "_dispatch_step_runner", _boom)
    code, diag = receipt.dispatch_step_runner_with_receipt(
        {"name": "item-qa", "step_runner": "qa"},
        stages=[],
        run_id="run-1",
        member_items=[],
        github_repo="",
        project="yoke",
        project_repo_path="",
        branch="main",
        first_item="",
        timeout_min=1,
        fresh=False,
        gate_branch="main",
        release_lineage="abc",
    )
    assert code == EXIT_DRIVER_SOURCE_DRIFT
    assert diag.startswith(DRIVER_SOURCE_DRIFT_PREFIX)


def test_execute_passes_pinned_env_to_the_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "yoke_cli.commands.deployment_execute.execution_connection_error",
        lambda _run_id: None,
    )
    monkeypatch.setattr(
        "yoke_cli.commands.deployment_execute.child_environment",
        lambda _run_id: {PINNED_RELEASE_ENV: "abc", "PATH": "/bin"},
    )
    with patch(
        "yoke_cli.commands.deployment_execute.subprocess.run",
    ) as pipeline:
        pipeline.return_value.returncode = 0
        out = io.StringIO()
        with redirect_stdout(out):
            rc = deployment_runs_execute(["run-1"])
    assert rc == 0
    assert pipeline.call_args.kwargs["env"][PINNED_RELEASE_ENV] == "abc"
    assert "frozen at" in out.getvalue()


def test_execute_leaves_relayed_env_unbound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "yoke_cli.commands.deployment_execute.execution_connection_error",
        lambda _run_id: None,
    )
    monkeypatch.setattr(
        "yoke_cli.commands.deployment_execute.child_environment",
        lambda _run_id: None,
    )
    with patch(
        "yoke_cli.commands.deployment_execute.subprocess.run",
    ) as pipeline:
        pipeline.return_value.returncode = 0
        rc = deployment_runs_execute(["run-1"])
    assert rc == 0
    assert "env" not in pipeline.call_args.kwargs

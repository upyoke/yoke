"""Onboarding commits on machines without a configured Git identity."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    git_output,
    run_git,
    write_https_config,
)
from yoke_cli import main as cli
from yoke_cli.config import project_git_bootstrap as boot
from yoke_cli.config.project_git_identity import DEFAULT_GIT_IDENTITY


@pytest.fixture
def clean_git_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    for key in tuple(os.environ):
        if key.startswith("GIT_") or key == "EMAIL":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    # Require explicit identity rather than Git guessing from this host's name.
    (home / ".gitconfig").write_text("[user]\n\tuseConfigOnly = true\n")
    return home


def _create(checkout: Path, config: Path) -> int:
    return cli.main(
        [
            "project",
            "create",
            str(checkout),
            "--slug",
            "demo",
            "--name",
            "Demo",
            "--public-item-prefix",
            "DMO",
            "--default-branch",
            "main",
            "--github-adoption",
            "disabled",
            "--config",
            str(config),
            "--yes",
            "--json",
        ]
    )


def test_fresh_onboarding_without_git_identity(
    tmp_path: Path,
    clean_git_home: Path,
    capsys,
) -> None:
    checkout = tmp_path / "app"
    global_before = (clean_git_home / ".gitconfig").read_bytes()
    with ProjectOnboardApi() as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        rc = _create(checkout, config)
    output = capsys.readouterr()
    assert rc == 0, output.err
    assert git_output(checkout, "rev-parse", "--verify", "HEAD")
    assert "repository-local" in output.err
    for key, value in DEFAULT_GIT_IDENTITY.items():
        assert git_output(checkout, "config", "--local", "--get", key) == value
    assert git_output(checkout, "log", "-1", "--format=%an <%ae>") == (
        f"{DEFAULT_GIT_IDENTITY['user.name']} <{DEFAULT_GIT_IDENTITY['user.email']}>"
    )
    assert (clean_git_home / ".gitconfig").read_bytes() == global_before


def test_resume_after_failed_initial_commit_has_head(
    tmp_path: Path,
    clean_git_home: Path,
    capsys,
) -> None:
    checkout = tmp_path / "app"
    checkout.mkdir()
    run_git(checkout, "init", "--initial-branch", "main")
    failed = subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "Initial commit"],
        cwd=checkout,
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    assert "identity unknown" in failed.stderr
    run_git(checkout, "config", "--local", "user.name", "Configured User")
    run_git(checkout, "config", "--local", "user.email", "user@example.invalid")
    with ProjectOnboardApi() as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        rc = _create(checkout, config)
    output = capsys.readouterr()
    assert rc == 0, output.err
    assert git_output(checkout, "rev-parse", "--verify", "HEAD")


@pytest.mark.parametrize("scope", ["local", "global"])
@pytest.mark.parametrize("present_key", ["user.name", "user.email", "both"])
def test_bootstrap_preserves_configured_identity_fields(
    tmp_path: Path,
    clean_git_home: Path,
    capsys,
    scope: str,
    present_key: str,
) -> None:
    checkout = tmp_path / "app"
    checkout.mkdir()
    values = {"user.name": "Configured User", "user.email": "user@example.invalid"}
    if scope == "local":
        run_git(checkout, "init", "--initial-branch", "main")
    for key, value in values.items():
        if present_key in (key, "both"):
            run_git(checkout, "config", f"--{scope}", key, value)
    global_before = (clean_git_home / ".gitconfig").read_bytes()
    # The shared initial-commit helper is also used when publishing a repo.
    from yoke_cli.config.project_publish_support import ensure_initial_commit

    if scope == "global":
        boot.prepare_checkout(checkout, "main")
    else:
        ensure_initial_commit(checkout, "main")
    for key, default in DEFAULT_GIT_IDENTITY.items():
        expected = values[key] if present_key in (key, "both") else default
        assert git_output(checkout, "config", "--get", key) == expected
    assert (clean_git_home / ".gitconfig").read_bytes() == global_before
    assert git_output(checkout, "rev-parse", "--verify", "HEAD")
    assert ("repository-local" in capsys.readouterr().err) == (present_key != "both")

"""Root-resolution tests for project scratch directory helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import project_scratch_dir as scratch
from runtime.api.domain.test_project_scratch_dir import (
    _patch_checkout_project,
    _patch_repo_root,
    _set_identity,
)


def test_env_override_wins_and_relative_roots_are_machine_home_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    yoke_home = tmp_path / "machine-home"
    _patch_repo_root(monkeypatch, repo)
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.setenv(scratch.machine_config.HOME_ENV, str(yoke_home))
    monkeypatch.setenv(scratch.ENV_KEY, "tmp")

    assert scratch.scratch_root("yoke") == (
        yoke_home
        / "tmp"
        / "yoke"
        / "sessions"
        / "test-session"
        / "runs"
        / "test-run"
    )


def test_machine_temp_root_when_env_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "machine-tmp"
    _patch_repo_root(monkeypatch, tmp_path)
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.delenv(scratch.ENV_KEY, raising=False)
    monkeypatch.setattr(
        scratch.machine_config,
        "temp_root",
        lambda path=None: str(configured),
    )

    assert scratch.scratch_root("yoke") == (
        configured
        / "yoke"
        / "sessions"
        / "test-session"
        / "runs"
        / "test-run"
    )


def test_machine_config_temp_root_when_env_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured"
    _patch_repo_root(monkeypatch, tmp_path)
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.delenv(scratch.ENV_KEY, raising=False)
    monkeypatch.setattr(
        scratch.machine_config,
        "temp_root",
        lambda path=None: str(configured),
    )

    assert scratch.scratch_root("yoke") == (
        configured
        / "yoke"
        / "sessions"
        / "test-session"
        / "runs"
        / "test-run"
    )


def test_os_tmpdir_fallback_includes_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch, session="buzz-session", run="run-2")
    monkeypatch.delenv(scratch.ENV_KEY, raising=False)
    monkeypatch.setattr(
        scratch.machine_config,
        "temp_root",
        lambda path=None: str(tmp_path / "bad-root"),
    )
    monkeypatch.setattr(
        scratch,
        "_ensure_writable_dir",
        lambda path: path != tmp_path / "bad-root",
    )
    monkeypatch.setattr(scratch.tempfile, "gettempdir", lambda: str(tmp_path))

    # The unwritable configured root emits the fallback warning before degrading
    # to the OS tmpdir; assert it here so it is captured, not leaked to the summary.
    with pytest.warns(RuntimeWarning, match="falling back"):
        resolved = scratch.scratch_root("buzz")
    assert resolved == (
        tmp_path
        / "yoke-scratch"
        / "buzz"
        / "sessions"
        / "buzz-session"
        / "runs"
        / "run-2"
    )


def test_macos_var_folders_fallback_prefers_short_tmp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scratch.tempfile, "gettempdir", lambda: "/var/folders/abc/T"
    )

    assert scratch._fallback_base() == Path("/tmp") / "yoke-scratch"


def test_override_root_appends_project_session_and_run_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override_root = tmp_path / "configured"
    _patch_repo_root(monkeypatch, tmp_path)
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch, session="sess", run="run")
    monkeypatch.setenv(scratch.ENV_KEY, str(override_root))

    assert scratch.scratch_root("yoke") == (
        override_root / "yoke" / "sessions" / "sess" / "runs" / "run"
    )
    assert scratch.scratch_root("buzz") == (
        override_root / "buzz" / "sessions" / "sess" / "runs" / "run"
    )


def test_global_scratch_root_is_project_agnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override_root = tmp_path / "configured"
    _patch_repo_root(monkeypatch, tmp_path)
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.setenv(scratch.ENV_KEY, str(override_root))

    assert scratch.global_scratch_root() == override_root
    assert scratch.scratch_root("buzz").parents[4] == scratch.global_scratch_root()

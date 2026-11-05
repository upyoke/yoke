# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import project_scratch_dir as scratch

from yoke_core.domain import project_scratch_roots as roots

from yoke_contracts.machine_config import runtime as machine_runtime

from yoke_core.domain import project_scratch_segments as segments


def _patch_repo_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(
        scratch, "find_repo_root", lambda start=None: root, raising=False
    )


def _patch_checkout_project(
    monkeypatch: pytest.MonkeyPatch, project_id: int | None = 1
) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.project_scratch_identity.resolve_project_namespace",
        lambda ref: {"yoke": "1", "externalwebapp": "2"}.get(ref, ref),
    )
    for module in (
        "yoke_core.domain.project_selection",
        "yoke_contracts.project_defaults",
    ):
        monkeypatch.setattr(
            f"{module}.default_project_for_directory",
            lambda _root: str(project_id) if project_id is not None else None,
        )


def _set_identity(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session: str = "test-session",
    run: str = "test-run",
) -> None:
    from yoke_core.domain.session_ambient_identity import AMBIENT_ENV_VARS

    for key in AMBIENT_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    for key in segments.RUN_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("YOKE_SESSION_ID", session)
    monkeypatch.setenv("YOKE_RUN_ID", run)

"""Planning-scratch coverage for workspace authority."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import project_scratch_dir as scratch
from yoke_core.domain.workspace_authority import (
    SESSION_ID_ENV_VAR,
    assert_target_under_session_work_authority,
)
from yoke_core.domain.workspace_authority_test_helpers import (
    PROJECT_REPO_ROOT,
    RETIRED_DISPATCH_ROOT,
    RUN_ID,
    SCRATCH_ROOT,
    SESSION_A,
    _seed_claim,
    _seed_item,
    _seed_project,
    _seed_session_status,
    conn,
    patch_conn,
)


def _setup_scratch(patch_conn, monkeypatch, item_id, status):
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    monkeypatch.setenv(scratch.ENV_KEY, SCRATCH_ROOT)
    monkeypatch.setenv("YOKE_RUN_ID", RUN_ID)
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(scratch, "_ensure_writable_dir", lambda path: True)
    _seed_project(patch_conn, PROJECT_REPO_ROOT)
    _seed_item(patch_conn, item_id=item_id, branch=f"YOK-{item_id}")
    _seed_claim(patch_conn, SESSION_A, item_id=item_id)
    _seed_session_status(patch_conn, SESSION_A, item_id, status)


def _dispatch_target(item_id: int, filename: str = "s.md") -> Path:
    return scratch.dispatch_inputs_dir(
        item_id=item_id,
        session_id="x",
        attempt=1,
        create=False,
    ) / filename


def test_planning_scratch_target_allowed_for_pre_implementation_session(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_scratch(patch_conn, monkeypatch, 1848, "refined-idea")
    assert_target_under_session_work_authority(_dispatch_target(1848))


def test_planning_scratch_target_refused_for_implementing_session(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_scratch(patch_conn, monkeypatch, 2024, "implementing")
    with pytest.raises(RuntimeError):
        assert_target_under_session_work_authority(_dispatch_target(2024))


def test_retired_data_sessions_target_refused_for_planning_session(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id = 555
    _setup_scratch(patch_conn, monkeypatch, item_id, "refined-idea")
    with pytest.raises(RuntimeError):
        assert_target_under_session_work_authority(Path(
            f"{PROJECT_REPO_ROOT}/{RETIRED_DISPATCH_ROOT}/"
            f"YOK-{item_id}/x/attempt-1/s.md",
        ))


def test_planning_non_scratch_target_still_refused(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_scratch(patch_conn, monkeypatch, 1848, "refined-idea")
    with pytest.raises(RuntimeError):
        assert_target_under_session_work_authority(
            Path("/opt/yoke-test/runtime/api/domain/foo.py")
        )

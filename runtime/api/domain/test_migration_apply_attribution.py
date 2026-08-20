"""Destructive apply requires attribution and a real migration model."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from runtime.api.domain.migration_boot_test_helpers import (
    RESTORE_POINT,
    apply_pending,
    connection,
    history as build_history,
    marks,
)
from yoke_contracts.session_lane import UNRESOLVED_EXECUTION_LANE
from yoke_core.domain.migration_apply_attribution import (
    IncompleteAttributionError,
    LaneAsModelNameError,
    collect_operator_attribution,
    refuse_lane_as_model_name,
    require_attribution,
)
from yoke_core.domain.migration_boot_apply import apply_pending as kernel_apply_pending
from yoke_core.domain.migration_yoke_ledger import YOKE_LEDGER_CONTRACT


def test_apply_pending_requires_attribution_and_model_name() -> None:
    parameters = inspect.signature(kernel_apply_pending).parameters
    assert parameters["attribution"].default is inspect.Parameter.empty
    assert parameters["model_name"].default is inspect.Parameter.empty


def test_omitting_attribution_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        kernel_apply_pending(
            object(),
            history=(),
            ledger=YOKE_LEDGER_CONTRACT,
            applied_by="test",
            running_version="",
            model_name="primary",
        )


def test_incomplete_attribution_names_every_missing_field() -> None:
    with pytest.raises(IncompleteAttributionError, match="session_id") as caught:
        require_attribution({"actor_id": "2"})
    message = str(caught.value)
    assert "source_branch" in message
    assert "source_commit" in message
    assert "Refuse to apply without attribution" in message


def test_apply_refuses_before_mutating_when_attribution_is_missing(
    tmp_path: Path,
) -> None:
    conn = connection()
    history = build_history(tmp_path, "0001_first")

    with pytest.raises(IncompleteAttributionError, match="session_id"):
        apply_pending(
            conn,
            history=history,
            applied_by="test",
            running_version="",
            attribution={},
            external_restore_point=RESTORE_POINT,
        )

    assert marks(conn) == []
    assert conn.execute("SELECT count(*) FROM migration_audit").fetchone()[0] == 0


def test_completed_receipt_records_attribution(tmp_path: Path) -> None:
    conn = connection()
    history = build_history(tmp_path, "0001_first")

    apply_pending(
        conn,
        history=history,
        applied_by="test",
        running_version="",
        external_restore_point=RESTORE_POINT,
    )

    row = conn.execute(
        "SELECT session_id, actor_id, source_branch, source_commit, model_name "
        "FROM migration_audit WHERE migration_name='0001_first'"
    ).fetchone()
    assert row == (
        "test-session",
        "test-actor",
        "main",
        "test-commit",
        "primary",
    )


def test_declared_model_name_that_collides_with_the_lane_sentinel_is_kept() -> None:
    assert refuse_lane_as_model_name(UNRESOLVED_EXECUTION_LANE) == "primary"
    assert (
        refuse_lane_as_model_name("primary", declared_models=["primary"]) == "primary"
    )


def test_execution_lane_is_refused_as_model_name() -> None:
    with pytest.raises(LaneAsModelNameError, match="execution lane"):
        refuse_lane_as_model_name("DARIUS")
    with pytest.raises(LaneAsModelNameError, match="execution lane"):
        refuse_lane_as_model_name("MUSKY", execution_lanes=["MUSKY"])


def test_apply_refuses_a_lane_value_in_model_name(tmp_path: Path) -> None:
    conn = connection()
    history = build_history(tmp_path, "0001_first")

    with pytest.raises(LaneAsModelNameError, match="DARIUS"):
        apply_pending(
            conn,
            history=history,
            applied_by="test",
            running_version="",
            model_name="DARIUS",
            external_restore_point=RESTORE_POINT,
        )

    assert marks(conn) == []


def test_operator_attribution_fails_closed_without_a_session(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.session_ambient_identity.resolve_ambient_session_id",
        lambda: None,
    )

    class _Conn:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("no lookup without a session")

    with pytest.raises(IncompleteAttributionError, match="session_id"):
        collect_operator_attribution(_Conn(), worktree=Path("/no/such/worktree"))

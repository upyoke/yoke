"""File-line checks are local/product-safe, not lifecycle-blocking core gates."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import backlog_updates_helpers as helpers
from yoke_core.domain.backlog_updates_helpers import (
    _FILE_LINE_GATE_TARGETS,
    _run_authoritative_status_gate,
    _run_file_line_gate,
)


def test_file_line_gate_targets_are_empty() -> None:
    assert _FILE_LINE_GATE_TARGETS == frozenset()


def test_file_line_gate_is_lifecycle_noop(tmp_path) -> None:
    for status in ("reviewing-implementation", "implemented", "done"):
        assert _run_file_line_gate(
            item_id=1,
            target_status=status,
            db_path=str(tmp_path / "fake.db"),
        ) is None


def test_authoritative_gate_still_composes_file_line_noop(tmp_path) -> None:
    db_path = str(tmp_path / "fake.db")
    with mock.patch.object(
        helpers, "_run_db_mutation_gate", return_value=None
    ), mock.patch.object(
        helpers, "_run_file_line_gate", return_value=None
    ) as mocked_file_line, mock.patch(
        "yoke_core.domain.backlog_architecture_gate_runner"
        "._run_architecture_impact_gate",
        return_value=None,
    ), mock.patch(
        "yoke_core.domain.backlog_authoritative_status_gate"
        "._evaluate_path_claim_boundary",
        return_value=None,
    ), mock.patch(
        "yoke_core.domain.backlog_authoritative_status_gate"
        "._evaluate_qa_verification",
        return_value=None,
    ):
        result = _run_authoritative_status_gate(
            item_id=1,
            target_status="implemented",
            db_path=db_path,
            qa_bypass=False,
            force=False,
        )

    assert result is None
    mocked_file_line.assert_called_once_with(
        item_id=1,
        target_status="implemented",
        db_path=db_path,
    )

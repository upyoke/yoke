"""QA-verification composer surfaces backend schema failures."""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.backlog_authoritative_status_gate import (
    _evaluate_qa_verification,
)


def _operational_error(message: str) -> Exception:
    return db_backend.operational_error_types()[0](message)


def test_missing_qa_schema_error_propagates() -> None:
    with mock.patch(
        "yoke_core.domain.qa_gates.check_verification_gate",
        side_effect=_operational_error("no such table: qa_runs"),
    ):
        with pytest.raises(db_backend.operational_error_types(), match="qa_runs"):
            _evaluate_qa_verification(
                item_id=42, target_status="release", db_path="/tmp/fake.db",
            )


def test_other_operational_errors_propagate() -> None:
    with mock.patch(
        "yoke_core.domain.qa_gates.check_verification_gate",
        side_effect=_operational_error("connection dropped"),
    ):
        with pytest.raises(db_backend.operational_error_types()):
            _evaluate_qa_verification(
                item_id=42, target_status="release", db_path="/tmp/fake.db",
            )

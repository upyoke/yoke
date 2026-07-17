"""QA-verification gate fallback on minimal legacy QA schemas.

``_evaluate_qa_verification`` swallows backend operational errors whose
message names a missing column/table (minimal legacy QA fixtures) and
re-raises every other operational error.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.backlog_authoritative_status_gate import (
    _evaluate_qa_verification,
)


def _operational_error(message: str) -> Exception:
    return db_backend.operational_error_types()[0](message)


def test_missing_qa_schema_skips_gate() -> None:
    with mock.patch(
        "yoke_core.domain.qa_gates.check_verification_gate",
        side_effect=_operational_error("no such table: qa_runs"),
    ):
        result = _evaluate_qa_verification(
            item_id=42, target_status="release", db_path="/tmp/fake.db",
        )
    assert result is None


def test_other_operational_errors_propagate() -> None:
    with mock.patch(
        "yoke_core.domain.qa_gates.check_verification_gate",
        side_effect=_operational_error("connection dropped"),
    ):
        with pytest.raises(db_backend.operational_error_types()):
            _evaluate_qa_verification(
                item_id=42, target_status="release", db_path="/tmp/fake.db",
            )

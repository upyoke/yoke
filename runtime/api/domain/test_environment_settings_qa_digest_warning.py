"""Environment-settings merge must not silently strand bound QA evidence."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_qa_requirement_target_rebind import (
    _stamp_requirement,
    _yoke_development,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_requirement_stranded_evidence import (
    StrandedQaEvidenceError,
    refuse_or_describe_stranded_evidence,
)


def test_digest_moving_write_refuses_without_acknowledgement() -> None:
    with test_database() as conn:
        environment_id = _yoke_development(conn)
        requirement_id = _stamp_requirement(
            conn, item_id=9201, environment_id=environment_id
        )
        with pytest.raises(StrandedQaEvidenceError, match="acknowledge") as exc:
            refuse_or_describe_stranded_evidence(
                conn,
                environment_id=int(environment_id),
                assignments={"hosts.app": "https://app.example.test"},
                acknowledge=False,
            )
        assert any(
            row["requirement_id"] == requirement_id for row in exc.value.stranded
        )


def test_unrelated_path_does_not_claim_stranded_evidence() -> None:
    with test_database() as conn:
        environment_id = _yoke_development(conn)
        _stamp_requirement(conn, item_id=9202, environment_id=environment_id)
        stranded = refuse_or_describe_stranded_evidence(
            conn,
            environment_id=int(environment_id),
            assignments={"pulumi.activation_state": "active"},
            acknowledge=False,
        )
        assert stranded == []


def test_acknowledged_write_names_the_stranded_rows() -> None:
    with test_database() as conn:
        environment_id = _yoke_development(conn)
        requirement_id = _stamp_requirement(
            conn, item_id=9203, environment_id=environment_id
        )
        stranded = refuse_or_describe_stranded_evidence(
            conn,
            environment_id=int(environment_id),
            assignments={"hosts.app": "https://app.example.test"},
            acknowledge=True,
        )
        assert stranded[0]["requirement_id"] == requirement_id
        assert stranded[0]["item_id"] == 9203

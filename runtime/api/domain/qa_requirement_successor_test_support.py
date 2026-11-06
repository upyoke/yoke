# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from datetime import datetime, timezone

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    record_case_verdict,
    seed_member_qa_case,
)

from runtime.api.fixtures.qa_declared_replacement_fixture import (
    corrected_case,
    declare,
    requirement_row,
)

from yoke_core.domain.qa_requirement_supersession import record_supersession

from yoke_core.domain.qa_requirement_successor import QaSuccessorError

from yoke_core.domain.qa_requirement_replacement import (
    QaReplacementError,
    point_at_replacement,
)

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status


def chain(conn):
    old = seed_member_qa_case(conn, run_id="run-successor-chain", member_item_id=9811)
    record_case_verdict(conn, old, "fail", evidence=True)
    middle = corrected_case(conn, failed_id=old, case_key="first-correction")
    declare(conn, old, "first-correction", [middle])
    record_case_verdict(conn, middle, "fail", evidence=True)
    final = corrected_case(conn, failed_id=middle, case_key="final-correction")
    declare(conn, middle, "final-correction", [final])
    record_case_verdict(conn, final, "pass", evidence=True)
    return old, middle, final


def inconsistent(conn, old, final):
    conn.execute(
        "UPDATE qa_requirements SET replacement_requirement_id=(SELECT id FROM qa_requirements WHERE replacement_requirement_id=%s AND id<>%s ORDER BY id DESC LIMIT 1), superseded_by_requirement_id=%s, supersession_rationale=%s, supersession_source='agent', superseded_at=%s WHERE id=%s",
        (final, old, final, "original correction history", "2026-01-01T00:00:00Z", old),
    )
    conn.commit()

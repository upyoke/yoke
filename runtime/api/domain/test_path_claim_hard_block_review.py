"""Tests for the path-claim hard-block classifier.

Covers the cleaned-up examples surfaced in the cleanup pass: the
``activation`` rows authored from path-claim overlap (without explicit
directional evidence) flag as over-hard, and the directional-evidence
case (``decision=directional`` rationale) does not flag.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain.project_seed_test_helpers import seed_project_identities

from yoke_core.domain import db_backend
from yoke_core.domain import path_claim_hard_block_review as review
from yoke_core.domain import schema, shepherd_init
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _apply_canonical_schema() -> None:
    """Build the full production schema + shepherd tables on the test DB.

    Zero-arg ``apply_schema`` strategy for :func:`init_test_db`:
    ``schema.cmd_init`` resolves its own connection from the repointed
    ``YOKE_PG_DSN``, then ``shepherd_init`` layers its tables
    (``item_dependencies`` etc.) onto a backend-factory connection.
    """
    schema.cmd_init()
    conn = db_backend.connect()
    try:
        seed_project_identities(conn)
        shepherd_init.cmd_init(conn)
    finally:
        conn.close()


def _open(db_path: str):
    return connect_test_db(db_path)


def _insert_dependency(
    conn,
    *,
    dependent: str,
    blocking: str,
    gate_point: str = "activation",
    source: str = "idea",
    rationale: str = "",
    satisfaction: str = "status:done",
) -> None:
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, source, "
        "rationale, evidence_json, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, "
        "'{}', '2026-05-13T00:00:00Z')",
        (dependent, blocking, gate_point, satisfaction, source, rationale),
    )
    conn.commit()


def _insert_item(
    conn,
    *,
    item_id: int,
    title: str,
    status: str,
    item_type: str = "issue",
) -> None:
    conn.execute(
        "INSERT INTO items "
        "(id, title, type, status, priority, created_at, updated_at, "
        "project_id, project_sequence) "
        "VALUES (%s, %s, %s, %s, 'medium', "
        "'2026-05-13T00:00:00Z', '2026-05-13T00:00:00Z', 1, %s)",
        (item_id, title, item_type, status, item_id),
    )
    conn.commit()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    with init_test_db(tmp_path, apply_schema=_apply_canonical_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = _open(db_path)
        try:
            yield {"db_path": db_path, "conn": conn}
        finally:
            conn.close()


# ----- review_activation_row (pure function) ---------------------------------


def test_non_activation_gate_point_not_applicable():
    r = review.review_activation_row(
        gate_point="coordination_only", source="idea",
        rationale="any text", dependent_status="refining-idea",
    )
    assert not r.over_hard
    assert "non-applicable" in r.reason


def test_directional_evidence_in_rationale_is_not_flagged():
    """Explicit directional evidence in rationale is the OK case."""
    r = review.review_activation_row(
        gate_point="activation",
        source="idea",
        rationale=(
            "decision=directional. shared_paths=docs/hook-parity-map.md. "
            "why_order_matters=upstream restructures the table this row "
            "edits"
        ),
        dependent_status="refined-idea",
        blocking_status="implementing",
    )
    assert not r.over_hard
    assert "directional evidence present" in r.reason


def test_coordination_only_rationale_on_activation_is_mislabel():
    """An activation row carrying decision=coordination_only is a clear mislabel."""
    r = review.review_activation_row(
        gate_point="activation",
        source="refine",
        rationale="decision=coordination_only. shared_paths=AGENTS.md",
        dependent_status="refined-idea",
    )
    assert r.over_hard
    assert "decision=coordination_only" in r.reason
    assert "coordination_only" in r.remediation


def test_path_claim_authored_without_directional_flagged():
    """Cleanup-pass shape: idea/refine source + path-mentioning rationale
    + no directional token = over-hard."""
    r = review.review_activation_row(
        gate_point="activation",
        source="idea",
        rationale=(
            "Path-claim overlap with YOK-1665 on "
            ".agents/skills/yoke/shepherd/design-checks.md"
        ),
        dependent_status="refining-idea",
        blocking_status="implementing",
    )
    assert r.over_hard
    assert "without decision=directional" in r.reason


def test_terminal_dependent_status_skipped():
    r = review.review_activation_row(
        gate_point="activation",
        source="idea",
        rationale="Path-claim overlap with YOK-X on AGENTS.md",
        dependent_status="done",
    )
    assert not r.over_hard
    assert "terminal" in r.reason


def test_terminal_blocking_status_is_already_satisfied():
    r = review.review_activation_row(
        gate_point="activation",
        source="idea",
        rationale="Path-claim overlap with YOK-X on AGENTS.md",
        dependent_status="refining-idea",
        blocking_status="done",
    )
    assert not r.over_hard
    assert "already satisfied" in r.reason


def test_implemented_dependent_status_still_reviewed():
    r = review.review_activation_row(
        gate_point="activation",
        source="idea",
        rationale="Path-claim overlap with YOK-X on AGENTS.md",
        dependent_status="implemented",
    )
    assert r.over_hard


def test_non_path_claim_source_does_not_flag():
    """Rows from operator/simulation sources without path indicators
    should not be flagged — the classifier targets idea/refine path-claim
    workflow authoring intent."""
    r = review.review_activation_row(
        gate_point="activation",
        source="operator",
        rationale="upstream feature must land first",
        dependent_status="refined-idea",
    )
    assert not r.over_hard


def test_path_claim_source_without_path_in_rationale_not_flagged():
    """Source=idea but rationale lacks concrete path evidence."""
    r = review.review_activation_row(
        gate_point="activation",
        source="idea",
        rationale="this work depends on the prior backend rewrite",
        dependent_status="refined-idea",
    )
    assert not r.over_hard


def test_path_claim_guidance_overlap_without_concrete_path_not_flagged():
    r = review.review_activation_row(
        gate_point="activation",
        source="idea",
        rationale=(
            "YOK-1685 overlaps path-claim intake guidance owned by YOK-1675; "
            "run after YOK-1675 so dependency teaching lands first"
        ),
        dependent_status="refined-idea",
        blocking_status="polishing-implementation",
    )
    assert not r.over_hard


def test_filepath_in_rationale_triggers_path_signal():
    r = review.review_activation_row(
        gate_point="activation",
        source="refine",
        rationale="touches runtime/api/domain/events.py same as YOK-X",
        dependent_status="refining-idea",
    )
    assert r.over_hard


# ----- scan_non_terminal_activation_rows (DB-aware) --------------------------


def test_scan_returns_empty_on_minimal_schema():
    """Self-skip path: no item_dependencies table → empty list."""
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    try:
        assert review.scan_non_terminal_activation_rows(conn) == []
    finally:
        conn.close()


def test_scan_handles_default_tuple_rows(env):
    """The domain helper should not require callers to set row_factory."""
    conn = env["conn"]
    _insert_item(conn, item_id=666, title="candidate", status="refined-idea")
    _insert_item(conn, item_id=665, title="upstream", status="implementing")
    _insert_dependency(
        conn,
        dependent="YOK-666",
        blocking="YOK-665",
        rationale="Path-claim overlap with YOK-665 on AGENTS.md",
        source="idea",
    )
    conn.close()

    tuple_conn = connect_test_db(env["db_path"])
    try:
        findings = review.scan_non_terminal_activation_rows(tuple_conn)
    finally:
        tuple_conn.close()
    assert len(findings) == 1
    assert findings[0].dependent_item == "YOK-666"


def test_scan_flags_path_claim_authored_without_directional(env):
    conn = env["conn"]
    _insert_item(conn, item_id=666, title="candidate", status="refined-idea")
    _insert_item(conn, item_id=665, title="upstream", status="implementing")
    _insert_dependency(
        conn,
        dependent="YOK-666",
        blocking="YOK-665",
        rationale=(
            "Path-claim overlap with YOK-665 on "
            ".agents/skills/yoke/shepherd/design-checks.md"
        ),
        source="idea",
    )
    findings = review.scan_non_terminal_activation_rows(conn)
    assert len(findings) == 1
    assert findings[0].dependent_item == "YOK-666"
    assert findings[0].blocking_item == "YOK-665"
    assert findings[0].review.over_hard


def test_scan_does_not_flag_directional_row(env):
    conn = env["conn"]
    _insert_item(conn, item_id=672, title="candidate", status="refined-idea")
    _insert_item(conn, item_id=665, title="upstream", status="implementing")
    _insert_dependency(
        conn,
        dependent="YOK-672",
        blocking="YOK-665",
        rationale=(
            "decision=directional. shared_paths=docs/hook-parity-map.md. "
            "why_order_matters=table reordering"
        ),
        source="idea",
    )
    findings = review.scan_non_terminal_activation_rows(conn)
    assert findings == []


def test_scan_does_not_flag_coordination_only_edges(env):
    conn = env["conn"]
    _insert_item(conn, item_id=666, title="c", status="refined-idea")
    _insert_item(conn, item_id=665, title="u", status="implementing")
    _insert_dependency(
        conn,
        dependent="YOK-666",
        blocking="YOK-665",
        gate_point="coordination_only",
        rationale=(
            "decision=coordination_only. shared_paths=AGENTS.md. "
            "independence_evidence=disjoint sections"
        ),
        source="idea",
    )
    findings = review.scan_non_terminal_activation_rows(conn)
    assert findings == []

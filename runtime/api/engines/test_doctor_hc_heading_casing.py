"""Tests for HC-heading-casing-canon.

Covers structured-field scanning, item_sections scanning, surface labelling,
finding aggregation by canonical form, and the per-surface remediation prompt.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.engines.doctor_hc_heading_casing import hc_heading_casing_canon
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_ITEM_COLUMNS = (
    "id INTEGER PRIMARY KEY",
    "spec TEXT",
    "design_spec TEXT",
    "technical_plan TEXT",
    "worktree_plan TEXT",
    "shepherd_log TEXT",
    "shepherd_caveats TEXT",
    "test_results TEXT",
    "deploy_log TEXT",
)


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    c.execute(f"CREATE TABLE items ({', '.join(_ITEM_COLUMNS)})")
    c.execute(
        "CREATE TABLE item_sections ("
        "item_id INTEGER NOT NULL, section_name TEXT NOT NULL, "
        "content TEXT, PRIMARY KEY (item_id, section_name))"
    )
    c.commit()
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_heading_casing_canon(conn, DoctorArgs(), rec)
    return rec


def _insert_item(conn, item_id: int, **fields) -> None:
    cols = ["id"] + list(fields)
    placeholders = ", ".join("%s" for _ in cols)
    vals = [item_id] + list(fields.values())
    conn.execute(
        f"INSERT INTO items ({', '.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()


def _insert_section(conn, item_id: int, section_name: str) -> None:
    conn.execute(
        "INSERT INTO item_sections (item_id, section_name, content) "
        "VALUES (%s, %s, '')",
        (item_id, section_name),
    )
    conn.commit()


def test_canonical_forms_only_pass(conn):
    _insert_item(
        conn, 1,
        spec="## Acceptance Criteria\n\n- foo\n\n## File Budget\n\n- bar",
        technical_plan="## Out of Scope\n\nnothing",
    )
    _insert_section(conn, 1, "Progress Log")
    rec = _run(conn)
    assert rec.results[-1].result == "PASS"


def test_off_canon_structured_field_warns_with_surface_label(conn):
    _insert_item(
        conn, 42,
        spec="## Acceptance criteria\n\n- foo",
    )
    rec = _run(conn)
    detail = rec.results[-1].detail
    assert rec.results[-1].result == "WARN"
    assert "Acceptance Criteria" in detail
    assert "Acceptance criteria" in detail
    assert "structured_field:spec" in detail
    assert "YOK-42" in detail
    assert "items.structured_field.replace" in detail


def test_off_canon_item_sections_warns_with_surface_label(conn):
    _insert_item(conn, 7, spec="canonical body, no headings")
    _insert_section(conn, 7, "progress log")
    rec = _run(conn)
    detail = rec.results[-1].detail
    assert rec.results[-1].result == "WARN"
    assert "Progress Log" in detail
    assert "progress log" in detail
    assert "item_sections" in detail
    assert "section_upsert" in detail


def test_mixed_canonical_and_off_canon_emits_only_off_canon(conn):
    _insert_item(
        conn, 9,
        spec=(
            "## Acceptance Criteria\n\n- canonical\n\n"
            "## File budget\n\n- off-canon"
        ),
    )
    rec = _run(conn)
    detail = rec.results[-1].detail
    assert rec.results[-1].result == "WARN"
    assert "File Budget" in detail
    assert "File budget" in detail
    # Canonical heading must not appear in the WARN detail as off-canon.
    assert "Acceptance criteria" not in detail
    # The off-canon line for YOK-9 names the file budget transition.
    assert "## File budget` -> `## File Budget" in detail


def test_finding_payload_names_canonical_and_observed(conn):
    _insert_item(conn, 11, spec="## Non-goals\n\nnothing")
    _insert_section(conn, 12, "out of scope")
    rec = _run(conn)
    detail = rec.results[-1].detail
    assert rec.results[-1].result == "WARN"
    assert "## Non-goals` -> `## Non-Goals" in detail
    assert "## out of scope` -> `## Out of Scope" in detail


def test_truncation_after_ten_items_per_canonical(conn):
    for i in range(1, 13):
        _insert_item(conn, i, spec="## File budget\n\n- off-canon")
    rec = _run(conn)
    detail = rec.results[-1].detail
    assert rec.results[-1].result == "WARN"
    assert "and 2 more" in detail


def test_clean_db_passes(conn):
    rec = _run(conn)
    assert rec.results[-1].result == "PASS"

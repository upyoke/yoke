"""Which items a document-scoped steering seat covers."""

from __future__ import annotations

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.steering_fleet_report_scope import (
    members_only,
    seat_members,
    sessions_only,
)
from yoke_core.domain.steering_scope_membership import (
    document_member_item_ids,
    item_coverage_target,
    item_document_slug,
    scope_document,
    scope_member_item_ids,
)
from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    seed_project,
    seed_strategy_doc,
)


AREA_PLAN = "AREA-PLAN"


class _Row:
    def __init__(self, item_id: int, session_id: str = "") -> None:
        self.item_id = item_id
        self.session_id = session_id


def _seed_item(conn, item_id: int, project_id: int = PROJECT_ALPHA) -> None:
    version = conn.execute(
        "SELECT current_version_id FROM workflows WHERE id = 'dash'"
    ).fetchone()
    now = iso8601_now()
    conn.execute(
        "INSERT INTO items "
        "(id, title, status, priority, created_at, updated_at, source, "
        "project_id, project_sequence, workflow_id, workflow_version_id) "
        "VALUES (%s, %s, 'implementing', 'medium', %s, %s, '2', "
        "%s, %s, 'dash', %s)",
        (item_id, f"Item {item_id}", now, now, project_id, item_id, version[0]),
    )
    conn.commit()


def _link(conn, item_id: int, slug: str, project_id: int = PROJECT_ALPHA) -> None:
    conn.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_at) "
        "VALUES (%s, %s, %s, %s)",
        (item_id, project_id, slug, iso8601_now()),
    )
    conn.commit()


def _world(conn):
    seed_project(conn, PROJECT_ALPHA, "alpha")
    seed_strategy_doc(conn, PROJECT_ALPHA, AREA_PLAN)
    _seed_item(conn, 9101)
    _seed_item(conn, 9102)
    _link(conn, 9101, AREA_PLAN)
    return conn


def test_scope_document_reads_the_one_refinement(test_db) -> None:
    assert scope_document({"project_id": 1}) is None
    assert scope_document({"project_id": 1, "document": AREA_PLAN}) == AREA_PLAN


def test_a_linked_item_names_its_document(test_db) -> None:
    conn = _world(test_db)
    assert item_document_slug(conn, 9101) == AREA_PLAN
    assert item_document_slug(conn, 9102) is None


def test_coverage_target_carries_project_item_and_document(test_db) -> None:
    conn = _world(test_db)
    assert item_coverage_target(
        conn, project_id=PROJECT_ALPHA, item_id=9101
    ) == {"project_id": PROJECT_ALPHA, "item_id": 9101, "document": AREA_PLAN}
    assert item_coverage_target(
        conn, project_id=PROJECT_ALPHA, item_id=9102
    ) == {"project_id": PROJECT_ALPHA, "item_id": 9102}
    assert item_coverage_target(conn, project_id=PROJECT_ALPHA, item_id=None) == {
        "project_id": PROJECT_ALPHA
    }


def test_membership_is_exactly_the_documents_linked_items(test_db) -> None:
    conn = _world(test_db)
    assert document_member_item_ids(
        conn, project_id=PROJECT_ALPHA, document=AREA_PLAN
    ) == {9101}
    assert scope_member_item_ids(
        conn, {"project_id": PROJECT_ALPHA, "document": AREA_PLAN}
    ) == {9101}


def test_a_project_seat_has_no_item_filter(test_db) -> None:
    """``None`` is the whole project, not an empty membership."""
    conn = _world(test_db)
    assert scope_member_item_ids(conn, {"project_id": PROJECT_ALPHA}) is None
    assert seat_members(conn, {"project_id": PROJECT_ALPHA}) is None


def test_filters_keep_everything_for_a_project_seat() -> None:
    rows = (_Row(1, "s1"), _Row(2, "s2"))
    assert members_only(rows, None) == rows
    assert sessions_only(rows, session_ids=(), members=None) == rows


def test_filters_narrow_to_the_seats_own_items_and_holders() -> None:
    rows = (_Row(1, "s1"), _Row(2, "s2"))
    assert members_only(rows, {1}) == (rows[0],)
    assert sessions_only(rows, session_ids={"s2"}, members={2}) == (rows[1],)

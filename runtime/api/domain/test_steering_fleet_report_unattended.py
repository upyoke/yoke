"""A linked item without its document seat is visible as unattended."""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.steering_fleet_report_unattended import unattended_linked_items
from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    SESSION_ALPHA,
    acquire_steering,
    seed_standard_steering_world,
    seed_strategy_doc,
)


def test_cross_project_link_is_unattended_until_document_seat_is_held(test_db):
    seed_standard_steering_world(test_db)
    seed_strategy_doc(test_db, PROJECT_ALPHA, "RELEASES")
    version = test_db.execute(
        "SELECT current_version_id FROM workflows WHERE id = 'dash'"
    ).fetchone()[0]
    now = iso8601_now()
    item_id = PROJECT_BETA * 100 + 1
    test_db.execute(
        "INSERT INTO items (id, title, status, priority, created_at, updated_at, "
        "source, project_id, project_sequence, workflow_id, workflow_version_id) "
        "VALUES (%s, 'Linked work', 'implementing', 'medium', %s, %s, '2', "
        "%s, %s, 'dash', %s)",
        (item_id, now, now, PROJECT_BETA, item_id, version),
    )
    test_db.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_at) "
        "VALUES (%s, %s, 'RELEASES', %s)",
        (item_id, PROJECT_ALPHA, now),
    )
    test_db.commit()
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_BETA)
    findings = unattended_linked_items(test_db, [PROJECT_BETA])
    assert len(findings) == 1
    assert "linked to RELEASES in alpha" in findings[0].finding
    assert "--project alpha --doc RELEASES" in findings[0].finding
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA, document="RELEASES")
    assert unattended_linked_items(test_db, [PROJECT_BETA]) == ()

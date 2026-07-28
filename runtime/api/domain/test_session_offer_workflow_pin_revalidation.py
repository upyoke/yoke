"""Auto-offer revalidation when workflow routing changes at one status."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from runtime.api.domain.test_workflow_item_migration_compatibility import (
    ITEM_ID,
    _publish_pair,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.test_sessions import _register
from runtime.api.test_constants import TEST_MODEL_ID
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.scheduler import compute_schedule
from yoke_core.domain.sessions_lifecycle import claim_work as real_claim_work
from yoke_core.domain.sessions_offer import session_offer_with_ownership
from yoke_core.domain.workflow_item_versioning import migrate_item_workflow_pin
from yoke_core.domain.workflow_registry import publish_workflow_version


def test_migration_first_offer_releases_claim_instead_of_stale_routing(
    test_db,
) -> None:
    """A claim acquired under a new pin cannot emit the old scheduled step."""
    source, _label_target = _publish_pair(test_db)
    target_definition = deepcopy(builtin_workflow_definition("issue")["definition"])
    target_definition["stages"][0]["label"] = "Offer routing target"
    advance_binding = next(
        binding
        for binding in target_definition["executor_bindings"]
        if binding["executor_id"] == "advance"
    )
    advance_binding["executor_id"] = "dash"
    target = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=target_definition,
    )
    _register(
        test_db,
        session_id="offer-pin-session",
        executor="claude-code",
    )
    migration_conn = connect_test_database(str(test_db.info.dbname))
    migration_result: dict = {}

    def migrate_before_claim(*args, **kwargs):
        migration_result.update(
            migrate_item_workflow_pin(
                migration_conn,
                item_id=ITEM_ID,
                target_version=int(target["version"]),
            )
        )
        return real_claim_work(*args, **kwargs)

    try:
        with patch(
            "yoke_core.domain.sessions_offer_candidates.claim_work",
            side_effect=migrate_before_claim,
        ):
            offer = session_offer_with_ownership(
                test_db,
                session_id="offer-pin-session",
                executor="claude-code",
                provider="anthropic",
                model=TEST_MODEL_ID,
                workspace="/tmp/work",
                supported_paths=["advance", "dash"],
                project_scope=["yoke"],
            )
    finally:
        migration_conn.close()

    assert migration_result["changed"] is True
    item = test_db.execute(
        "SELECT status, workflow_version_id FROM items WHERE id=%s",
        (ITEM_ID,),
    ).fetchone()
    assert item[0] == "implementing"
    assert int(item[1]) == int(target["version_id"])
    assert offer["action_hint"] == "no_work"
    assert offer["new_claim"] is None
    assert offer["claims"] == []
    assert offer["schedule_result"].selected_step.next_step.value == "advance"
    assert int(offer["schedule_result"].selected_step.workflow_version_id) == int(
        source["version_id"]
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM work_claims "
            "WHERE session_id='offer-pin-session' AND released_at IS NULL"
        ).fetchone()[0]
        == 0
    )
    skip = offer["chain_skip_memory"][-1]
    assert skip["skip_reason"] == "stale_lifecycle_post_claim"
    assert skip["expected_status"] == skip["current_status"] == "implementing"
    assert skip["expected_next_step"] == "advance"

    fresh_schedule = compute_schedule(
        test_db,
        project_scope=["yoke"],
        session_id="offer-pin-session",
    )
    assert fresh_schedule.selected_step is not None
    assert fresh_schedule.selected_step.item_id == f"YOK-{ITEM_ID}"
    assert fresh_schedule.selected_step.next_step.value == "dash"
    assert int(fresh_schedule.selected_step.workflow_version_id) == int(
        target["version_id"]
    )

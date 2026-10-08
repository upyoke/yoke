"""Existing workflow pins require explicit migration before level amendments."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_workflow_canon_auto_follow import _seed_generation, _state
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.item_posture_amend import amend_item_posture
from yoke_core.domain.item_posture_amend_guards import ItemPostureAmendError
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_item_versioning import (
    inspect_item_workflow_pin,
    migrate_item_workflow_pin,
)
from yoke_core.domain.workflow_registry import converge_builtin_workflows


def test_existing_pin_survives_boot_then_explicit_migration_allows_override() -> None:
    with test_database() as conn:
        historical = next(
            generation
            for generation in canon_generations("dash")
            if generation.canon_version == 9
        )
        source_version_id = _seed_generation(conn, "dash", historical.canon_version)
        item = insert_item(conn, id=2941, workflow_id="dash", status="idea")
        item_id = int(item["id"])
        ref = render_item_ref(conn, item_id, required=True)
        original = inspect_item_workflow_pin(conn, item_id)
        converge_builtin_workflows(conn)
        target = _state(conn, "dash")
        assert target["version"] > original["workflow_version"]
        assert target["canon_adopted_from_version"] == original["workflow_version"]
        before = inspect_item_workflow_pin(conn, item_id)
        assert before == original
        assert before["workflow_version_id"] == source_version_id
        assert "level" not in before["policies"]["item_posture_allowlist"]

        override = {"max": "SENIOR", "reason": "bounded staffing"}
        with pytest.raises(ItemPostureAmendError) as error:
            amend_item_posture(
                conn, item_id=item_id, key="level", value=override, reason="staffing"
            )
        message = str(error.value)
        assert f"dash@{before['workflow_version']} does not allow" in message
        assert "Deploying new workflow versions does not change" in message
        assert f"workflows item migrate {ref} --version N --preview" in message
        assert "operator-started authority" in message
        assert inspect_item_workflow_pin(conn, item_id) == before

        preview = migrate_item_workflow_pin(
            conn, item_id=item_id, target_version=target["version"], preview=True
        )
        assert preview["conflicts"] == []
        assert inspect_item_workflow_pin(conn, item_id) == before
        migrated = migrate_item_workflow_pin(
            conn, item_id=item_id, target_version=target["version"]
        )
        assert migrated["after"]["status"] == before["status"]
        assert migrated["after"]["active_lanes"] == before["active_lanes"]
        amended = amend_item_posture(
            conn, item_id=item_id, key="level", value=override, reason="staffing"
        )
        assert amended["after"]["level"] == override
        assert historical.digest == before["definition_digest"]

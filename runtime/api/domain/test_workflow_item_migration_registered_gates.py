"""Catalog-wide reached-stage gate compatibility for workflow migration."""

from __future__ import annotations

from copy import deepcopy

import pytest

from runtime.api.domain.test_workflow_item_migration_compatibility import (
    ITEM_ID,
    _pin,
    _seed_path_claim,
)
from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_gate_catalog import (
    GATE_APPROVAL,
    GATE_QA_VERIFICATION,
    workflow_gate_catalog,
)
from yoke_core.domain.workflow_item_versioning import (
    migrate_item_workflow_pin,
)
from yoke_core.domain.workflow_registry import publish_workflow_version


def _stage(definition: dict, stage_id: str) -> dict:
    return next(stage for stage in definition["stages"] if stage["id"] == stage_id)


def _publish_gate_pair(
    test_db,
    *,
    stage_id: str,
    source_gate: dict | None = None,
    target_gate: dict | None = None,
    remove_gate_id: str | None = None,
) -> tuple[dict, dict]:
    source_definition = deepcopy(builtin_workflow_definition("issue")["definition"])
    source_definition["stages"][0]["label"] = "Gate migration candidate"
    if source_gate is not None:
        _stage(source_definition, stage_id)["gates"].append(source_gate)
    source = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=source_definition,
    )
    insert_item(
        test_db,
        id=ITEM_ID,
        workflow_id="issue",
        status="implementing",
    )

    target_definition = deepcopy(source_definition)
    target_definition["stages"][0]["label"] = "Gate migration target"
    target_stage = _stage(target_definition, stage_id)
    if remove_gate_id is not None:
        target_stage["gates"] = [
            gate for gate in target_stage["gates"] if gate["id"] != remove_gate_id
        ]
    if target_gate is not None:
        target_stage["gates"].append(target_gate)
    target = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=target_definition,
    )
    _seed_path_claim(test_db)
    return source, target


def _registered_gate_refs() -> list[dict]:
    refs = []
    for gate in workflow_gate_catalog():
        modes = gate["modes"]
        if not modes:
            refs.append({"id": gate["id"]})
            continue
        refs.extend({"id": gate["id"], "mode": mode["id"]} for mode in modes)
    return refs


def _expected_message(gate_id: str) -> str:
    if gate_id == GATE_APPROVAL:
        return "unsatisfied approval"
    if gate_id == GATE_QA_VERIFICATION:
        return "unsatisfied QA gate"
    return gate_id


@pytest.mark.parametrize(
    "gate_ref",
    _registered_gate_refs(),
    ids=lambda gate: f"{gate['id']}-{gate['mode']}" if "mode" in gate else gate["id"],
)
def test_every_registered_gate_is_rejected_when_added_to_reached_stage(
    test_db,
    gate_ref: dict,
) -> None:
    _source, target = _publish_gate_pair(
        test_db,
        stage_id="idea",
        target_gate=gate_ref,
    )
    before = _pin(test_db)

    with pytest.raises(
        WorkflowRegistryError,
        match=_expected_message(str(gate_ref["id"])),
    ):
        migrate_item_workflow_pin(
            test_db,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )

    assert _pin(test_db) == before


def test_reached_gate_mode_change_is_an_unsatisfied_target_gate(test_db) -> None:
    _source, target = _publish_gate_pair(
        test_db,
        stage_id="idea",
        source_gate={"id": "db_mutation", "mode": "joint"},
        target_gate={"id": "db_mutation", "mode": "evidence"},
        remove_gate_id="db_mutation",
    )

    with pytest.raises(
        WorkflowRegistryError,
        match="db_mutation.*evidence",
    ):
        migrate_item_workflow_pin(
            test_db,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )


def test_gate_added_only_after_current_stage_remains_compatible(test_db) -> None:
    _source, target = _publish_gate_pair(
        test_db,
        stage_id="reviewing-implementation",
        target_gate={"id": "plan_simulation"},
    )

    result = migrate_item_workflow_pin(
        test_db,
        item_id=ITEM_ID,
        target_version=int(target["version"]),
    )

    assert result["changed"] is True


def test_reached_gate_removal_remains_compatible(test_db) -> None:
    _source, target = _publish_gate_pair(
        test_db,
        stage_id="implementing",
        remove_gate_id="check_hard_blocks",
    )

    result = migrate_item_workflow_pin(
        test_db,
        item_id=ITEM_ID,
        target_version=int(target["version"]),
    )

    assert result["changed"] is True

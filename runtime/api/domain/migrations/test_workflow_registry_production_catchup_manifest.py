from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.portable_migration import apply_manifest, parse_manifest_text


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "workflow_registry_production_catchup.migration.json"
)
_MODULES = (
    "workflow_file_budget_policy_revision",
    "workflow_item_shape_contract",
    "workflow_item_worktree_records",
    "workflow_item_worktree_source_fields_contract",
    "path_claim_task_bindings",
    "qa_command_plan_cutover",
    "workflow_item_browser_qa_metadata_contract",
)
_INSTALLER_MODULES = {
    "installer_campaign_plan_rows",
    "installer_campaign_screen_ready_plan",
    "installer_campaign_project_screen_plan",
    "installer_campaign_key_settle_plan",
    "installer_campaign_current_text_plan",
}


def _payload() -> dict[str, object]:
    text = _MANIFEST.read_text(encoding="utf-8")
    payload = json.loads(text)
    validate_manifest_payload(payload)
    parse_manifest_text(text)
    return payload


def test_production_catchup_is_exact_digest_bound_and_fleet_safe() -> None:
    payload = _payload()

    assert tuple(payload["profile"]["migration_modules"]) == _MODULES
    assert set(payload["module_sources"]) == set(_MODULES)
    assert not _INSTALLER_MODULES.intersection(payload["module_sources"])
    for source in payload["module_sources"].values():
        assert migration_source_digest(_ROOT / source["path"]) == source["sha256"]


def test_worktree_backfill_precedes_task_binding_and_source_contraction() -> None:
    payload = _payload()
    modules = tuple(payload["profile"]["migration_modules"])

    assert modules.index("workflow_item_worktree_records") < modules.index(
        "workflow_item_worktree_source_fields_contract"
    )
    assert modules.index("workflow_item_worktree_records") < modules.index(
        "path_claim_task_bindings"
    )


def test_production_catchup_applies_as_one_ordered_unit(test_db) -> None:
    manifest = parse_manifest_text(_MANIFEST.read_text(encoding="utf-8"))

    result = apply_manifest(test_db, manifest)

    assert result.modules == _MODULES

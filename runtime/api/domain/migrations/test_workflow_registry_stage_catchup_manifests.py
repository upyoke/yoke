from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.migrations.installer_campaign_key_settle_plan import (
    apply as apply_key_settled,
)
from yoke_core.domain.migrations.installer_campaign_plan_rows import (
    apply as apply_plan_rows,
)
from yoke_core.domain.migrations.installer_campaign_project_screen_plan import (
    apply as apply_project_screen,
)
from yoke_core.domain.migrations.installer_campaign_screen_ready_plan import (
    apply as apply_screen_ready,
)
from yoke_core.domain.portable_migration import apply_manifest, parse_manifest_text


_ROOT = Path(__file__).resolve().parents[4]
_DIRECTORY = Path(__file__).parent
_CONTROL_PLANE = _DIRECTORY / (
    "workflow_registry_stage_control_plane_catchup.migration.json"
)
_TENANT = _DIRECTORY / "workflow_registry_stage_tenant_catchup.migration.json"
_COMPATIBLE_MODULES = (
    "qa_requirement_execution_snapshot",
    "qa_plan_execution_records",
    "path_claim_task_bindings",
)


def _payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    parse_manifest_text(path.read_text(encoding="utf-8"))
    for source in payload["module_sources"].values():
        assert migration_source_digest(_ROOT / source["path"]) == source["sha256"]
    return payload


def test_stage_control_plane_batch_is_exact_and_digest_bound() -> None:
    payload = _payload(_CONTROL_PLANE)
    assert tuple(payload["profile"]["migration_modules"]) == (
        *_COMPATIBLE_MODULES,
        "installer_campaign_current_text_plan",
    )


def test_stage_tenant_batch_excludes_the_successive_plan_chain() -> None:
    payload = _payload(_TENANT)
    assert tuple(payload["profile"]["migration_modules"]) == _COMPATIBLE_MODULES
    assert not {
        "installer_campaign_plan_rows",
        "installer_campaign_screen_ready_plan",
        "installer_campaign_project_screen_plan",
        "installer_campaign_key_settle_plan",
        "installer_campaign_current_text_plan",
    }.intersection(payload["module_sources"])


def test_stage_control_plane_batch_applies_after_current_predecessors(test_db) -> None:
    apply_plan_rows(test_db)
    apply_screen_ready(test_db)
    apply_project_screen(test_db)
    apply_key_settled(test_db)
    manifest = parse_manifest_text(_CONTROL_PLANE.read_text(encoding="utf-8"))

    result = apply_manifest(test_db, manifest)

    assert result.modules == (
        *_COMPATIBLE_MODULES,
        "installer_campaign_current_text_plan",
    )


def test_stage_tenant_batch_reapplies_without_drift(test_db) -> None:
    manifest = parse_manifest_text(_TENANT.read_text(encoding="utf-8"))

    first = apply_manifest(test_db, manifest)
    second = apply_manifest(test_db, manifest)

    assert first.modules == _COMPATIBLE_MODULES
    assert second.modules == _COMPATIBLE_MODULES

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.portable_migration import apply_manifest, parse_manifest_text


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "hosted_runtime_schema_convergence.migration.json"
)
_MODULES = (
    "workflow_supporting_schema_records",
    "qa_requirement_execution_snapshot",
    "qa_plan_execution_records",
    "qa_plan_execution_deployment_subject",
    "qa_execution_environment_target",
    "qa_plan_agent_review_records",
    "epic_task_scope_state",
    "events_actor_identity",
)


def _payload() -> dict[str, object]:
    text = _MANIFEST.read_text(encoding="utf-8")
    payload = json.loads(text)
    validate_manifest_payload(payload)
    parse_manifest_text(text)
    return payload


def test_convergence_batch_is_exact_digest_bound() -> None:
    payload = _payload()

    assert tuple(payload["profile"]["migration_modules"]) == _MODULES
    assert tuple(payload["module_sources"]) == _MODULES
    for source in payload["module_sources"].values():
        assert migration_source_digest(_ROOT / source["path"]) == source["sha256"]


def test_convergence_batch_preserves_dependency_order() -> None:
    modules = tuple(_payload()["profile"]["migration_modules"])

    assert modules.index("qa_requirement_execution_snapshot") < modules.index(
        "qa_execution_environment_target"
    )
    assert modules.index("qa_plan_execution_records") < modules.index(
        "qa_plan_execution_deployment_subject"
    )
    assert modules.index("qa_plan_execution_deployment_subject") < modules.index(
        "qa_plan_agent_review_records"
    )
    assert modules[-1] == "events_actor_identity"


def test_convergence_batch_applies_as_one_ordered_unit(test_db) -> None:
    manifest = parse_manifest_text(_MANIFEST.read_text(encoding="utf-8"))

    result = apply_manifest(test_db, manifest)

    assert result.modules == _MODULES

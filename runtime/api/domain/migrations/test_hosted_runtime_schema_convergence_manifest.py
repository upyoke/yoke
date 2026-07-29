from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations import workflow_supporting_schema_records
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.portable_migration import apply_manifest, parse_manifest_text
from yoke_core.domain.schema_common import _table_exists


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
_STANDALONE_MANIFESTS = tuple(
    Path(__file__).with_name(f"{module}.migration.json") for module in _MODULES
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


def test_convergence_batch_declares_complete_surface_union() -> None:
    combined = _payload()["profile"]["affected_surfaces"]
    expected: dict[str, set[str]] = {}
    for path in _STANDALONE_MANIFESTS:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for surface in payload["profile"]["affected_surfaces"]:
            expected.setdefault(surface["table"], set()).update(surface["columns"])

    actual = {
        surface["table"]: set(surface["columns"])
        for surface in combined
    }

    assert actual == expected


def test_convergence_batch_applies_as_one_ordered_unit(test_db) -> None:
    manifest = parse_manifest_text(_MANIFEST.read_text(encoding="utf-8"))

    result = apply_manifest(test_db, manifest)

    assert result.modules == _MODULES


def test_convergence_batch_rolls_back_every_module_when_final_module_refuses(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = parse_manifest_text(_MANIFEST.read_text(encoding="utf-8"))
    marker_table = "convergence_transaction_probe"
    original_apply = workflow_supporting_schema_records.apply

    def apply_with_marker(conn) -> None:
        conn.execute(f"CREATE TABLE {marker_table} (id INTEGER PRIMARY KEY)")
        original_apply(conn)

    monkeypatch.setattr(
        workflow_supporting_schema_records,
        "apply",
        apply_with_marker,
    )
    test_db.execute(
        "INSERT INTO events "
        "(event_id, source_type, session_id, event_kind, event_type, event_name, "
        "envelope, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "convergence-refusal",
            "backend",
            "session-convergence-refusal",
            "migration",
            "migration",
            "ConvergenceRefusal",
            '{"user_id":"retained-human-identity"}',
            "2026-07-29T21:00:00Z",
        ),
    )
    test_db.commit()

    with pytest.raises(AssertionError, match="envelope has 1 non-null"):
        apply_manifest(test_db, manifest)

    assert not _table_exists(test_db, marker_table)

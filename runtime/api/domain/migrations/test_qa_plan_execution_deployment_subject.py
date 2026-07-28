"""Governed migration coverage for deployment-run plan executions."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.migrations.qa_plan_execution_deployment_subject import (
    MIGRATION_NAME,
    apply,
    invariants,
)


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "qa_plan_execution_deployment_subject.migration.json"
)


def test_governed_manifest_is_valid_and_source_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    assert migration_source_digest(_ROOT / source["path"]) == source["sha256"]


def test_apply_expands_item_execution_schema_idempotently(test_db) -> None:
    apply(test_db)
    invariants(test_db)
    apply(test_db)
    invariants(test_db)

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from runtime.api.domain.migrations import (
    workflow_registry_runtime_ownership_recovery as source_wrapper,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.workflow_registry_runtime_ownership_recovery import (
    MIGRATION_NAME,
    apply,
    invariants,
)

_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "workflow_registry_runtime_ownership_recovery.migration.json"
)


def test_governed_manifest_is_valid_and_digest_bound():
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"]["workflow_registry_runtime_ownership_recovery"]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


def test_source_checkout_wrapper_exposes_packaged_migration():
    assert source_wrapper.MIGRATION_NAME == MIGRATION_NAME
    assert source_wrapper.apply is apply
    assert source_wrapper.invariants is invariants

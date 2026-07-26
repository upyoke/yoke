from __future__ import annotations

import hashlib
import json
from pathlib import Path

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.installer_campaign_plan_rows import (
    EXPECTED_CASE_KEYS,
    apply,
    invariants,
)


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "installer_campaign_plan_rows.migration.json"
)


def test_governed_manifest_is_valid_and_digest_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"]["installer_campaign_plan_rows"]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


def test_migration_replaces_markdown_catalog_with_executable_plan(test_db) -> None:
    apply(test_db)
    invariants(test_db)

    rows = test_db.execute(
        "SELECT c.case_key,c.method_id,c.host_baselines,c.entry_surface,"
        "c.required_completion "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "WHERE p.slug='installer-campaign' ORDER BY c.position"
    ).fetchall()

    assert tuple(row["case_key"] for row in rows) == EXPECTED_CASE_KEYS
    assert all(
        row["entry_surface"] and row["required_completion"]
        for row in rows
        if row["method_id"].startswith("terminal-")
    )
    assert sum(
        max(1, len(json.loads(row["host_baselines"])))
        for row in rows
    ) == 12
    assert not any(
        row["case_key"].rsplit("-", 1)[-1].isdigit()
        for row in rows
    )

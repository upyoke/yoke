from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.installer_campaign_key_settle_cases import (
    KEY_SETTLED_INSTALLER_CAMPAIGN_CASES,
    key_settled_campaign_digest,
)
from yoke_core.domain.installer_campaign_project_screen_cases import (
    project_screen_campaign_digest,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.migrations.installer_campaign_key_settle_plan import (
    CAMPAIGN_CONTRACT_SHA256,
    MIGRATION_NAME,
    apply,
    invariants,
)
from yoke_core.domain.migrations.installer_campaign_plan_rows import (
    apply as apply_base,
)
from yoke_core.domain.migrations.installer_campaign_project_screen_plan import (
    CAMPAIGN_CONTRACT_SHA256 as PROJECT_SCREEN_CAMPAIGN_SHA256,
    apply as apply_project_screen,
)
from yoke_core.domain.migrations.installer_campaign_screen_ready_plan import (
    apply as apply_screen_ready,
)


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "installer_campaign_key_settle_plan.migration.json"
)


def test_governed_manifest_is_valid_and_digest_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    assert migration_source_digest(_ROOT / source["path"]) == source["sha256"]


def test_key_settled_contract_is_append_only_and_digest_bound() -> None:
    assert project_screen_campaign_digest() == PROJECT_SCREEN_CAMPAIGN_SHA256
    assert key_settled_campaign_digest() == CAMPAIGN_CONTRACT_SHA256
    assert MIGRATION_NAME == "installer_campaign_key_settle_plan"


def test_local_project_input_waits_for_the_project_screen() -> None:
    cases = {case["case_key"]: case for case in KEY_SETTLED_INSTALLER_CAMPAIGN_CASES}
    actions = {
        action["step"]: action
        for action in cases["apply-handoff"]["method_config"]["actions"]
    }
    assert actions["project-mode"]["ready_text"] == [
        "Set up a project.",
        "Where's the code?",
    ]


def test_migration_replaces_only_future_case_specification(test_db) -> None:
    apply_base(test_db)
    apply_screen_ready(test_db)
    apply_project_screen(test_db)
    before = test_db.execute("SELECT COUNT(*) FROM qa_plan_cases").fetchone()

    apply(test_db)
    invariants(test_db)

    after = test_db.execute("SELECT COUNT(*) FROM qa_plan_cases").fetchone()
    assert after["count"] == before["count"]


def test_migration_reapplies_without_drift(test_db) -> None:
    apply_base(test_db)
    apply_screen_ready(test_db)
    apply_project_screen(test_db)
    apply(test_db)
    apply(test_db)
    invariants(test_db)

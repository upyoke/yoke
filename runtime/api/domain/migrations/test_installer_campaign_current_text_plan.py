from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.installer_campaign_current_text_cases import (
    CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES,
    current_text_campaign_digest,
)
from yoke_core.domain.installer_campaign_key_settle_cases import (
    key_settled_campaign_digest,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.migrations.installer_campaign_current_text_plan import (
    CAMPAIGN_CONTRACT_SHA256,
    MIGRATION_NAME,
    apply,
    invariants,
)
from yoke_core.domain.migrations.installer_campaign_key_settle_plan import (
    CAMPAIGN_CONTRACT_SHA256 as KEY_SETTLED_CAMPAIGN_SHA256,
    apply as apply_key_settled,
)
from yoke_core.domain.migrations.installer_campaign_plan_rows import (
    apply as apply_base,
)
from yoke_core.domain.migrations.installer_campaign_project_screen_plan import (
    apply as apply_project_screen,
)
from yoke_core.domain.migrations.installer_campaign_screen_ready_plan import (
    apply as apply_screen_ready,
)


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "installer_campaign_current_text_plan.migration.json"
)


def test_governed_manifest_is_valid_and_digest_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    assert migration_source_digest(_ROOT / source["path"]) == source["sha256"]


def test_current_text_contract_is_append_only_and_digest_bound() -> None:
    assert key_settled_campaign_digest() == KEY_SETTLED_CAMPAIGN_SHA256
    assert current_text_campaign_digest() == CAMPAIGN_CONTRACT_SHA256
    assert MIGRATION_NAME == "installer_campaign_current_text_plan"


def test_cold_start_cases_assert_only_observable_current_text() -> None:
    cases = {
        case["case_key"]: case for case in CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES
    }
    configs = cases["cold-start-hosted"]["method_config"]["baseline_configs"]
    assert set(configs) == {"fresh-host", "shell-preconfigured"}
    for config in configs.values():
        assert "Starting Yoke onboard" not in config["expected_text"]
        assert "Where should this Yoke live?" in config["expected_text"]
        assert "Next: make it execution-ready." in config["expected_text"]


def test_migration_replaces_only_future_case_specification(test_db) -> None:
    apply_base(test_db)
    apply_screen_ready(test_db)
    apply_project_screen(test_db)
    apply_key_settled(test_db)
    before = test_db.execute("SELECT COUNT(*) FROM qa_plan_cases").fetchone()

    apply(test_db)
    invariants(test_db)

    after = test_db.execute("SELECT COUNT(*) FROM qa_plan_cases").fetchone()
    assert after["count"] == before["count"]


def test_migration_reapplies_without_drift(test_db) -> None:
    apply_base(test_db)
    apply_screen_ready(test_db)
    apply_project_screen(test_db)
    apply_key_settled(test_db)
    apply(test_db)
    apply(test_db)
    invariants(test_db)

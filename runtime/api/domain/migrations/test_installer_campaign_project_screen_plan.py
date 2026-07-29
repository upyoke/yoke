from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.installer_campaign_project_screen_cases import (
    PROJECT_SCREEN_INSTALLER_CAMPAIGN_CASES,
    project_screen_campaign_digest,
)
from yoke_core.domain.installer_campaign_screen_ready_cases import (
    screen_ready_campaign_digest,
)
from yoke_core.domain.migrations.installer_campaign_project_screen_plan import (
    CAMPAIGN_CONTRACT_SHA256,
    MIGRATION_NAME,
    apply,
    invariants,
)
from yoke_core.domain.migrations.installer_campaign_plan_rows import (
    apply as apply_base,
)
from yoke_core.domain.migrations.installer_campaign_screen_ready_plan import (
    CAMPAIGN_CONTRACT_SHA256 as SCREEN_READY_CAMPAIGN_SHA256,
    apply as apply_screen_ready,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "installer_campaign_project_screen_plan.migration.json"
)


def test_governed_manifest_is_valid_and_digest_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    digest = migration_source_digest(_ROOT / source["path"])
    assert digest == source["sha256"]


def test_project_screen_contract_is_append_only_and_digest_bound() -> None:
    assert screen_ready_campaign_digest() == SCREEN_READY_CAMPAIGN_SHA256
    assert project_screen_campaign_digest() == CAMPAIGN_CONTRACT_SHA256
    assert MIGRATION_NAME == "installer_campaign_project_screen_plan"


def test_project_mode_input_waits_for_its_source_screen() -> None:
    cases = {
        case["case_key"]: case for case in PROJECT_SCREEN_INSTALLER_CAMPAIGN_CASES
    }
    for config in cases["cold-start-hosted"]["method_config"][
        "baseline_configs"
    ].values():
        actions = {action["step"]: action for action in config["actions"]}
        assert actions["project-mode"]["ready_text"] == [
            "Set up a project.",
            "Where's the code?",
        ]
        assert actions["project-mode-machine-only"]["ready_text"] == [
            "Set up a project.",
            "Where's the code?",
        ]
        assert actions["project-mode-machine-only"]["keys"] == [
            "Down",
            "Down",
            "Down",
            "Down",
            "Enter",
        ]


def test_apply_handoff_asserts_the_observed_public_installer_flow() -> None:
    cases = {
        case["case_key"]: case for case in PROJECT_SCREEN_INSTALLER_CAMPAIGN_CASES
    }
    expected = cases["apply-handoff"]["method_config"]["expected_text"]
    assert "Starting Yoke onboard" not in expected
    assert "Yoke is already on your PATH." in expected
    assert "Next: make it execution-ready." in expected


def test_migration_replaces_only_future_case_specification(test_db) -> None:
    apply_base(test_db)
    apply_screen_ready(test_db)
    before = test_db.execute("SELECT COUNT(*) FROM qa_plan_cases").fetchone()

    apply(test_db)
    invariants(test_db)

    after = test_db.execute("SELECT COUNT(*) FROM qa_plan_cases").fetchone()
    assert after["count"] == before["count"]


def test_migration_reapplies_without_drift(test_db) -> None:
    apply_base(test_db)
    apply_screen_ready(test_db)
    apply(test_db)
    apply(test_db)
    invariants(test_db)

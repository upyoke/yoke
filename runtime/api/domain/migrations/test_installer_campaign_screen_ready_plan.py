from __future__ import annotations

import hashlib
import json
from pathlib import Path

from yoke_core.domain.installer_campaign_cases import campaign_contract_digest
from yoke_core.domain.installer_campaign_screen_ready_cases import (
    SCREEN_READY_INSTALLER_CAMPAIGN_CASES,
    screen_ready_campaign_digest,
)
from yoke_core.domain.migrations.installer_campaign_plan_rows import (
    CAMPAIGN_CONTRACT_SHA256 as BASE_CAMPAIGN_SHA256,
    apply as apply_base,
)
from yoke_core.domain.migrations.installer_campaign_screen_ready_plan import (
    CAMPAIGN_CONTRACT_SHA256,
    MIGRATION_NAME,
    apply,
    invariants,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "installer_campaign_screen_ready_plan.migration.json"
)


def test_governed_manifest_is_valid_and_digest_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


def test_screen_ready_contract_is_append_only_and_digest_bound() -> None:
    assert campaign_contract_digest() == BASE_CAMPAIGN_SHA256
    assert screen_ready_campaign_digest() == CAMPAIGN_CONTRACT_SHA256
    assert MIGRATION_NAME == "installer_campaign_screen_ready_plan"


def test_screen_ready_contract_gates_terminal_input() -> None:
    cases = {case["case_key"]: case for case in SCREEN_READY_INSTALLER_CAMPAIGN_CASES}
    for config in cases["cold-start-hosted"]["method_config"][
        "baseline_configs"
    ].values():
        actions = {action["step"]: action for action in config["actions"]}
        assert "project-mode" not in actions
        assert "project-mode-machine-only" not in actions
        assert actions["hosted-connected"]["ready_text"] == ["Yoke token connected."]
        assert actions["machine-github-backlog"]["ready_text"] == ["Connect GitHub?"]
        assert actions["apply"]["ready_text"] == [
            "Review what Yoke will save.",
            "Apply",
        ]


def test_migration_replaces_only_future_case_specification(test_db) -> None:
    apply_base(test_db)
    before = test_db.execute("SELECT COUNT(*) FROM qa_plan_cases").fetchone()

    apply(test_db)
    invariants(test_db)

    after = test_db.execute("SELECT COUNT(*) FROM qa_plan_cases").fetchone()
    assert after["count"] == before["count"]


def test_migration_reapplies_without_drift(test_db) -> None:
    apply_base(test_db)
    apply(test_db)
    apply(test_db)
    invariants(test_db)

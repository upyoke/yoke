from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.installer_campaign_catalog import (
    INSTALLER_CAMPAIGN_SCENARIOS,
)
from yoke_core.domain.installer_campaign_cases import (
    campaign_contract_digest,
)
from yoke_core.domain.machine_qa_method_contracts import (
    validate_machine_method_config,
)
from yoke_core.domain.migrations.installer_campaign_plan_rows import (
    CAMPAIGN_CONTRACT_SHA256,
    EXPECTED_CASE_KEYS,
    INSTALLER_CAMPAIGN_CASES,
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


def test_code_owned_catalog_preserves_every_absorbed_scenario() -> None:
    assert len(INSTALLER_CAMPAIGN_SCENARIOS) == 188
    assert len({row.source_id for row in INSTALLER_CAMPAIGN_SCENARIOS}) == 188
    assert sum(
        row.source_id.startswith("GITHUB-")
        for row in INSTALLER_CAMPAIGN_SCENARIOS
    ) == 53
    assert sum(
        not row.source_id.startswith("GITHUB-")
        for row in INSTALLER_CAMPAIGN_SCENARIOS
    ) == 135
    assert EXPECTED_CASE_KEYS == tuple(
        row.source_id.lower()
        for row in INSTALLER_CAMPAIGN_SCENARIOS
    )
    assert campaign_contract_digest() == CAMPAIGN_CONTRACT_SHA256

    by_id = {
        row.source_id: row
        for row in INSTALLER_CAMPAIGN_SCENARIOS
    }
    assert by_id["MAC-011"].flow == (
        "Full `curl | bash` in Terminal.app, wizard left by `Quit`"
    )
    assert by_id["GITHUB-053"].host_profile == "prepared-git"
    assert by_id["GITHUB-053"].expected_outcome.startswith(
        "Unbind deletes only that project's binding"
    )
    for scenario, case in zip(
        INSTALLER_CAMPAIGN_SCENARIOS,
        INSTALLER_CAMPAIGN_CASES,
        strict=True,
    ):
        assert f"Source scenario: {scenario.source_id}." in case["instructions"]
        assert (
            f"Required host profile or precondition: "
            f"{scenario.host_profile}."
        ) in case["instructions"]
        assert f"Exercise this flow: {scenario.flow}." in case["instructions"]
        assert case["expected_outcome"] == scenario.expected_outcome
        assert validate_machine_method_config(
            case["method_id"],
            case["method_config"],
            entry_surface=case["entry_surface"],
            required_completion=case["required_completion"],
        )


def _campaign_state(conn) -> list[tuple]:
    rows = conn.execute(
        "SELECT p.slug,p.name,p.description,c.case_key,c.position,c.method_id,"
        "c.instructions,c.expected_outcome,c.method_config,c.host_baselines,"
        "c.entry_surface,c.required_completion "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "WHERE p.slug='installer-campaign' ORDER BY c.position"
    ).fetchall()
    return [tuple(row) for row in rows]


def test_migration_replaces_catalog_and_reapplies_without_semantic_drift(
    test_db,
) -> None:
    apply(test_db)
    invariants(test_db)

    rows = test_db.execute(
        "SELECT c.case_key,c.method_id,c.host_baselines,c.entry_surface,"
        "c.required_completion "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "WHERE p.slug='installer-campaign' ORDER BY c.position"
    ).fetchall()

    assert tuple(row["case_key"] for row in rows) == EXPECTED_CASE_KEYS
    assert len(rows) == 188
    assert all(
        row["entry_surface"] and row["required_completion"]
        for row in rows
        if row["method_id"].startswith("terminal-")
    )
    assert sum(
        max(1, len(json.loads(row["host_baselines"])))
        for row in rows
    ) == 188
    assert Counter(row["method_id"] for row in rows) == {
        "terminal-check": 5,
        "terminal-inspection": 180,
        "machine-state-check": 3,
    }

    cases_by_key = {
        case["case_key"]: case
        for case in INSTALLER_CAMPAIGN_CASES
    }
    assert all(
        all(step["send"] for step in case["method_config"]["steps"])
        for case in cases_by_key.values()
        if case["method_id"] == "terminal-inspection"
    )
    assert cases_by_key["install-smoke-001"]["method_config"]["steps"][0][
        "send"
    ] == "Enter"
    assert cases_by_key["term-010"]["method_config"]["steps"][0]["send"] == "C-c"
    assert cases_by_key["term-008"]["method_config"]["steps"][0]["send"] == "C-j"
    assert cases_by_key["github-013"]["method_config"]["steps"][0][
        "send"
    ] == "Escape"
    assert cases_by_key["github-024"]["method_config"]["steps"][0][
        "send"
    ] == "Enter"
    assert cases_by_key["mac-007"]["method_config"] == {
        "assertions": [{
            "argv": [
                "/bin/zsh",
                "-c",
                "command -v uv >/dev/null && command -v uvx >/dev/null "
                "&& command -v yoke >/dev/null",
            ],
        }],
    }

    first_state = _campaign_state(test_db)
    apply(test_db)
    invariants(test_db)

    assert _campaign_state(test_db) == first_state
    assert len(first_state) == len(EXPECTED_CASE_KEYS)

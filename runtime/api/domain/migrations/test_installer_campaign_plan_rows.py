from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import psycopg

from runtime.api.fixtures.pg_testdb import dsn_for_test_database
from runtime.api.domain.migrations.installer_campaign_assertions import (
    contains_key,
    terminal_configs,
)
from yoke_core.domain.installer_campaign_cases import (
    EXPECTED_CASE_KEYS,
    EXPECTED_METHOD_COUNTS,
    EXPECTED_REQUIREMENT_COUNT,
    INSTALLER_CAMPAIGN_CASES,
    campaign_contract_digest,
)
from yoke_core.domain.machine_qa_method_contracts import (
    validate_machine_method_config,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.installer_campaign_plan_rows import (
    CAMPAIGN_CONTRACT_SHA256,
    apply,
    invariants,
)


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name("installer_campaign_plan_rows.migration.json")
_CASE_KEYS = (
    "path-on-shell",
    "welcome-frame",
    "cold-start-hosted",
    "hosted-connect",
    "path-repair",
    "apply-handoff",
    "connect-wait",
    "review-frame",
    "token-perms",
    "universe-born",
)
_BASELINE_CASES = {
    "cold-start-hosted": ["fresh-host", "shell-preconfigured"],
    "path-on-shell": ["fresh-host", "shell-preconfigured"],
}


def test_governed_manifest_is_valid_and_digest_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"]["installer_campaign_plan_rows"]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


def test_source_is_exact_approved_ten_case_contract() -> None:
    assert EXPECTED_CASE_KEYS == _CASE_KEYS
    assert len(INSTALLER_CAMPAIGN_CASES) == 10
    assert [case["position"] for case in INSTALLER_CAMPAIGN_CASES] == list(range(1, 11))
    assert Counter(case["method_id"] for case in INSTALLER_CAMPAIGN_CASES) == {
        "terminal-check": 4,
        "terminal-inspection": 3,
        "machine-state-check": 3,
    }
    assert EXPECTED_METHOD_COUNTS == {
        "terminal-check": 4,
        "terminal-inspection": 3,
        "machine-state-check": 3,
    }
    assert {
        case["case_key"]: case["host_baselines"]
        for case in INSTALLER_CAMPAIGN_CASES
        if case["host_baselines"]
    } == _BASELINE_CASES
    assert len(_BASELINE_CASES) == 2
    assert (
        sum(max(1, len(case["host_baselines"])) for case in INSTALLER_CAMPAIGN_CASES)
        == EXPECTED_REQUIREMENT_COUNT
        == 12
    )
    assert all(
        not contains_key(case["method_config"], "execution_blocker")
        for case in INSTALLER_CAMPAIGN_CASES
    )
    assert campaign_contract_digest() == CAMPAIGN_CONTRACT_SHA256

    for case in INSTALLER_CAMPAIGN_CASES:
        assert validate_machine_method_config(
            case["method_id"],
            case["method_config"],
            entry_surface=case["entry_surface"],
            required_completion=case["required_completion"],
        )
        for baseline in case["host_baselines"]:
            assert validate_machine_method_config(
                case["method_id"],
                case["method_config"],
                entry_surface=case["entry_surface"],
                required_completion=case["required_completion"],
                host_baseline=baseline,
            )
        if case["method_id"].startswith("terminal-"):
            assert case["entry_surface"]
            assert case["required_completion"]
            for config in terminal_configs(case):
                actions = config["actions"]
                assert isinstance(actions, list)
                assert case["required_completion"] in {
                    action["step"] for action in actions
                }
                assert all(
                    "C-c" not in action.get("keys", [])
                    and not any(
                        str(key).startswith("paste_file:")
                        for key in action.get("keys", [])
                    )
                    for action in actions
                )
                assert "stage_files" not in config
        else:
            assert case["entry_surface"] is None
            assert case["required_completion"] is None


def test_baseline_order_proves_prerequisites_before_mutating_install() -> None:
    keys = [case["case_key"] for case in INSTALLER_CAMPAIGN_CASES]
    assert keys.index("path-on-shell") < keys.index("cold-start-hosted")
    fresh_group = [
        case["case_key"]
        for case in INSTALLER_CAMPAIGN_CASES
        if "fresh-host" in case["host_baselines"]
    ]
    shell_group = [
        case["case_key"]
        for case in INSTALLER_CAMPAIGN_CASES
        if "shell-preconfigured" in case["host_baselines"]
    ]
    assert fresh_group == ["path-on-shell", "cold-start-hosted"]
    assert shell_group == ["path-on-shell", "cold-start-hosted"]

    installer_shim = (_ROOT / "packaging/public-installer/install").read_text(
        encoding="utf-8"
    )
    ensure_uv = installer_shim.split("ensure_uv() {", 1)[1].split(
        "validate_uv_installer_url() {",
        1,
    )[0]
    assert ensure_uv.index("need_command uv && return 0") < ensure_uv.index(
        "print_welcome_banner"
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


def test_migration_replaces_catalog_and_reapplies_without_drift(test_db) -> None:
    apply(test_db)
    invariants(test_db)

    rows = test_db.execute(
        "SELECT c.case_key,c.method_id,c.host_baselines,c.method_config "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "WHERE p.slug='installer-campaign' ORDER BY c.position"
    ).fetchall()
    assert tuple(row["case_key"] for row in rows) == _CASE_KEYS
    assert len(rows) == 10
    assert Counter(row["method_id"] for row in rows) == {
        "terminal-check": 4,
        "terminal-inspection": 3,
        "machine-state-check": 3,
    }
    assert sum(max(1, len(json.loads(row["host_baselines"]))) for row in rows) == 12
    assert all(
        not contains_key(json.loads(row["method_config"]), "execution_blocker")
        for row in rows
    )

    first_state = _campaign_state(test_db)
    apply(test_db)
    invariants(test_db)
    assert _campaign_state(test_db) == first_state


def test_migration_accepts_default_psycopg_tuple_rows(test_db) -> None:
    dsn = dsn_for_test_database(test_db.info.dbname)
    with psycopg.connect(dsn) as tuple_conn:
        apply(tuple_conn)
        invariants(tuple_conn)
        apply(tuple_conn)
        invariants(tuple_conn)

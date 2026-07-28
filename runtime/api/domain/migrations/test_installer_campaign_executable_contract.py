"""Governed convergence coverage for the executable installer campaign."""

from __future__ import annotations

import json
from pathlib import Path

import psycopg

from runtime.api.domain.migrations import (
    installer_campaign_executable_contract as source_wrapper,
)
from runtime.api.fixtures.pg_testdb import dsn_for_test_database
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.migrations.installer_campaign_executable_contract import (
    MIGRATION_NAME,
    PLAN_DESCRIPTION,
    apply,
    invariants,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "installer_campaign_executable_contract.migration.json"
)
_EXPECTED_KEYS = (
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


def test_governed_manifest_is_valid_and_closure_digest_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    assert migration_source_digest(_ROOT / source["path"]) == source["sha256"]


def test_source_checkout_wrapper_exposes_packaged_migration() -> None:
    assert MIGRATION_NAME == "installer_campaign_executable_contract"
    assert source_wrapper.MIGRATION_NAME == MIGRATION_NAME
    assert source_wrapper.apply is apply
    assert source_wrapper.invariants is invariants


def _seed_stale_catalog(conn) -> None:
    plan = create_plan(
        conn,
        project="yoke",
        slug="installer-campaign",
        name="Installer campaign",
        description="Stale prose-derived installer catalog.",
    )
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": "install-smoke-001",
                "position": 1,
                "method_id": "terminal-check",
                "instructions": "Legacy prose.",
                "expected_outcome": "Legacy outcome.",
                "method_config": {
                    "steps": [
                        {
                            "key": "install-smoke-001",
                            "expect": "Yoke",
                        }
                    ]
                },
                "entry_surface": "printf legacy",
                "required_completion": "install-smoke-001",
            },
            {
                "case_key": "upgrade-002",
                "position": 188,
                "method_id": "terminal-inspection",
                "instructions": "Legacy prose.",
                "expected_outcome": "Legacy outcome.",
                "method_config": {
                    "steps": [
                        {
                            "key": "upgrade-002",
                            "expect": "Yoke",
                            "send": "Enter",
                        }
                    ]
                },
                "entry_surface": "printf legacy",
                "required_completion": "upgrade-002",
            },
        ],
    )
    conn.commit()


def _campaign_state(conn) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT p.name,p.description,c.case_key,c.position,c.method_id,"
            "c.method_config,c.host_baselines,c.entry_surface,"
            "c.required_completion "
            "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
            "WHERE p.slug='installer-campaign' ORDER BY c.position"
        ).fetchall()
    ]


def test_apply_replaces_completed_catalog_shape_and_reapplies_cleanly(test_db) -> None:
    _seed_stale_catalog(test_db)

    apply(test_db)
    invariants(test_db)

    rows = _campaign_state(test_db)
    assert tuple(row[2] for row in rows) == _EXPECTED_KEYS
    assert len(rows) == 10
    assert rows[0][1] == PLAN_DESCRIPTION

    first_state = rows
    apply(test_db)
    invariants(test_db)
    assert _campaign_state(test_db) == first_state


def test_apply_accepts_default_psycopg_tuple_rows(test_db) -> None:
    dsn = dsn_for_test_database(test_db.info.dbname)
    with psycopg.connect(dsn) as tuple_conn:
        _seed_stale_catalog(tuple_conn)
        apply(tuple_conn)
        invariants(tuple_conn)
        apply(tuple_conn)
        invariants(tuple_conn)

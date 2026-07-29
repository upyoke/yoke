"""Portable convergence coverage for the current installer campaign."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.installer_campaign_current_text_cases import (
    CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import (
    migration_source_digest,
    migration_source_files,
)
from yoke_core.domain.migrations.installer_campaign_current_plan import (
    MIGRATION_NAME,
    apply,
    invariants,
)


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "installer_campaign_current_plan.migration.json"
)


def _plan_id(conn) -> int:
    row = conn.execute(
        "SELECT p.id FROM qa_plans p JOIN projects pr ON pr.id=p.project_id "
        "WHERE pr.slug='yoke' AND p.slug='installer-campaign'"
    ).fetchone()
    assert row is not None
    return int(row[0])


def _future_state(conn) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT c.case_key,c.position,c.method_id,c.instructions,"
            "c.expected_outcome,c.method_config,c.host_baselines,"
            "c.entry_surface,c.required_completion "
            "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
            "JOIN projects pr ON pr.id=p.project_id "
            "WHERE pr.slug='yoke' AND p.slug='installer-campaign' "
            "ORDER BY c.position"
        ).fetchall()
    ]


def test_manifest_is_valid_and_binds_complete_source_closure() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    source_path = _ROOT / source["path"]
    assert migration_source_digest(source_path) == source["sha256"]
    assert {path.name for path in migration_source_files(source_path)} == {
        "installer_campaign_current_plan.py",
    }


def test_absent_project_is_explicit_noop(test_db) -> None:
    test_db.execute("UPDATE projects SET slug='renamed-yoke' WHERE slug='yoke'")
    test_db.execute(
        "DROP TABLE qa_plan_cases, qa_plans, qa_methods, qa_requirements CASCADE"
    )
    test_db.commit()

    apply(test_db)
    invariants(test_db)

    assert test_db.execute(
        "SELECT COUNT(*) FROM projects WHERE slug='yoke'"
    ).fetchone()[0] == 0


def test_existing_project_without_plan_creates_final_plan(test_db) -> None:
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_plans WHERE slug='installer-campaign'"
    ).fetchone()[0] == 0

    apply(test_db)
    invariants(test_db)

    assert len(_future_state(test_db)) == len(
        CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES
    )


def test_old_plan_is_replaced_with_final_contract(test_db) -> None:
    apply(test_db)
    plan_id = _plan_id(test_db)
    test_db.execute(
        "UPDATE qa_plans SET name='Old name', description='Old description' "
        "WHERE id=%s",
        (plan_id,),
    )
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions='Retired instructions' "
        "WHERE plan_id=%s AND case_key='path-on-shell'",
        (plan_id,),
    )
    test_db.execute(
        "DELETE FROM qa_plan_cases "
        "WHERE plan_id=%s AND case_key='universe-born'",
        (plan_id,),
    )
    test_db.commit()

    apply(test_db)
    invariants(test_db)

    plan = test_db.execute(
        "SELECT name,description FROM qa_plans WHERE id=%s",
        (plan_id,),
    ).fetchone()
    assert tuple(plan) == (
        "Installer campaign",
        "Physical Test Mac proof for the public installer, onboarding "
        "Terminal frames, and resulting machine state.",
    )


def test_reapply_is_idempotent(test_db) -> None:
    apply(test_db)
    first = _future_state(test_db)

    apply(test_db)
    invariants(test_db)

    assert _future_state(test_db) == first

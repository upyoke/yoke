"""Governed migration coverage for workflow-supporting records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from runtime.api.domain.migrations import (
    workflow_supporting_schema_records as source_wrapper,
)
from yoke_core.domain.decision_request_contract import DECISION_EVENT_ROWS
from yoke_core.domain.machine_qa_method_contracts import MACHINE_METHODS
from yoke_core.domain.machine_qa_pack import (
    MACHINE_QA_PACK,
    load_machine_qa_methods,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.installer_campaign_plan_rows import (
    apply as apply_installer_campaign,
    invariants as installer_campaign_invariants,
)
from yoke_core.domain.migrations.workflow_supporting_schema_records import (
    MIGRATION_NAME,
    apply,
    invariants,
)
from yoke_core.domain.qa_catalog_schema import BUILTIN_QA_METHODS
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.strategy_execution_events import (
    STRATEGY_EXECUTION_EVENT_ROWS,
)


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "workflow_supporting_schema_records.migration.json"
)

_QA_REQUIREMENT_COLUMNS = (
    "expected_outcome",
    "host_baseline",
    "instructions",
    "method_config",
    "method_id",
    "plan_case_key",
    "plan_id",
    "workflow_transition_id",
)
_QA_RUN_COLUMNS = ("capture_degraded_reason", "case_outcome")


def test_governed_manifest_is_valid_and_digest_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


def test_source_checkout_wrapper_exposes_packaged_migration() -> None:
    assert source_wrapper.MIGRATION_NAME == MIGRATION_NAME
    assert source_wrapper.apply is apply
    assert source_wrapper.invariants is invariants


def _remove_supporting_schema(conn) -> None:
    for column in _QA_REQUIREMENT_COLUMNS:
        conn.execute(f"ALTER TABLE qa_requirements DROP COLUMN IF EXISTS {column}")
    for column in _QA_RUN_COLUMNS:
        conn.execute(f"ALTER TABLE qa_runs DROP COLUMN IF EXISTS {column}")

    for table in (
        "qa_plan_project_defaults",
        "qa_plan_item_attachments",
        "qa_plan_cases",
        "qa_plans",
        "qa_methods",
        "addressed_event_deliveries",
        "decision_request_role_authorities",
        "decision_request_actor_authorities",
        "decision_requests",
        "strategy_doc_claims",
        "item_strategy_docs",
        "test_machine_verifications",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {table}")

    conn.execute("ALTER TABLE strategy_doc_revisions DROP COLUMN IF EXISTS session_id")
    conn.execute("ALTER TABLE strategy_docs DROP COLUMN IF EXISTS parent_slug")


def _count(conn, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _machine_method_state(conn) -> dict[str, tuple[str, ...]]:
    rows = conn.execute(
        "SELECT id,name,description,source_kind,source_ref,executor_id,"
        "required_capability_kind,verdict_path,verdict_contract,"
        "evidence_contract,success_policy_id,success_policy_params,"
        "concurrency_mode FROM qa_methods"
    ).fetchall()
    return {
        str(row[0]): tuple(str(value) for value in row[1:])
        for row in rows
        if str(row[3]) == "pack" and str(row[4]) == MACHINE_QA_PACK
    }


def _expected_machine_method_state() -> dict[str, tuple[str, ...]]:
    _, methods = load_machine_qa_methods()
    return {
        method["id"]: (
            method["name"],
            method["description"],
            "pack",
            MACHINE_QA_PACK,
            method["executor_id"],
            method["required_capability_kind"],
            method["verdict_path"],
            method["verdict_contract"],
            method["evidence_contract"],
            "all-pass",
            "{}",
            method["concurrency_mode"],
        )
        for method in methods
    }


def test_apply_propagates_absent_schema_and_repeat_apply_is_stable(test_db) -> None:
    _remove_supporting_schema(test_db)
    for table in (
        "item_strategy_docs",
        "decision_requests",
        "qa_methods",
        "test_machine_verifications",
    ):
        assert not _table_exists(test_db, table)
    assert not _column_exists(test_db, "strategy_docs", "parent_slug")
    assert not _column_exists(test_db, "qa_requirements", "plan_id")

    apply(test_db)
    invariants(test_db)

    expected_method_ids = {str(method["id"]) for method in BUILTIN_QA_METHODS}
    actual_method_ids = {
        str(row[0])
        for row in test_db.execute(
            "SELECT id FROM qa_methods WHERE source_kind='built_in'"
        ).fetchall()
    }
    assert expected_method_ids <= actual_method_ids
    assert set(_machine_method_state(test_db)) == set(MACHINE_METHODS)

    expected_event_names = {
        str(row[0]) for row in (*DECISION_EVENT_ROWS, *STRATEGY_EXECUTION_EVENT_ROWS)
    }
    actual_event_names = {
        str(row[0])
        for row in test_db.execute("SELECT event_name FROM event_registry").fetchall()
    }
    assert expected_event_names <= actual_event_names

    seeded_counts = {
        table: _count(test_db, table) for table in ("event_registry", "qa_methods")
    }
    apply(test_db)
    invariants(test_db)
    assert seeded_counts == {table: _count(test_db, table) for table in seeded_counts}


def test_apply_repairs_machine_methods_before_installer_plan_validation(
    test_db,
) -> None:
    _remove_supporting_schema(test_db)
    apply(test_db)
    assert _machine_method_state(test_db) == _expected_machine_method_state()

    test_db.execute(
        "UPDATE qa_methods SET name='stale',source_kind='built_in',"
        "source_ref=NULL WHERE id='terminal-check'"
    )
    test_db.execute("DELETE FROM qa_methods WHERE id='machine-state-check'")
    with pytest.raises(AssertionError, match="Machine QA Pack methods"):
        invariants(test_db)

    apply(test_db)
    invariants(test_db)
    assert _machine_method_state(test_db) == _expected_machine_method_state()

    apply_installer_campaign(test_db)
    installer_campaign_invariants(test_db)

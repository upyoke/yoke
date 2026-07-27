from __future__ import annotations

import hashlib
import json
from pathlib import Path

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.qa_command_plan_cutover import (
    apply,
    invariants,
)


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "qa_command_plan_cutover.migration.json"
)


def test_governed_manifest_is_valid_and_digest_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    profile = payload["profile"]
    assert profile["compatibility_class"] == "pre_merge_breaking"
    assert profile["migration_strategy"] == "hard_cutover"
    source = payload["module_sources"]["qa_command_plan_cutover"]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


def _cutover_state(conn) -> dict[str, list[tuple]]:
    plans = conn.execute(
        "SELECT p.id,p.slug,p.name,p.description,p.retired_at,"
        "c.id,c.case_key,c.position,c.method_id,c.method_config "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "WHERE p.slug IN ('registered-command-quick','pre-merge-verification') "
        "ORDER BY p.slug,c.position"
    ).fetchall()
    defaults = conn.execute(
        "SELECT project_id,workflow_id,transition_id,qa_phase,plan_id "
        "FROM qa_plan_project_defaults "
        "WHERE plan_id IN ("
        "SELECT id FROM qa_plans WHERE slug IN ("
        "'registered-command-quick','pre-merge-verification')) "
        "ORDER BY project_id,workflow_id,transition_id,plan_id"
    ).fetchall()
    return {
        "plans": [tuple(row) for row in plans],
        "defaults": [tuple(row) for row in defaults],
    }


def test_cutover_moves_commands_removes_legacy_and_reapplies_cleanly(test_db) -> None:
    test_db.execute(
        "INSERT INTO project_structure("
        "project_id, family, attachment_value, attachment_kind, entry_key, "
        "payload, created_at, updated_at"
        ") VALUES (1, 'command_definitions', 'project', '', 'quick', %s, "
        "'2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z')",
        (json.dumps({"command": "python3 -m pytest -q"}),),
    )
    test_db.execute(
        "INSERT INTO project_structure("
        "project_id, family, attachment_value, attachment_kind, entry_key, "
        "payload, created_at, updated_at"
        ") VALUES (1, 'merge_verification', 'project', '', '', %s, "
        "'2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z')",
        (json.dumps({
            "command": "python3 -m pytest",
            "timeout_seconds": 1800,
        }),),
    )
    test_db.commit()

    apply(test_db)
    invariants(test_db)

    row = test_db.execute(
        "SELECT p.slug, c.method_id, c.method_config "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "WHERE p.slug='registered-command-quick'"
    ).fetchone()
    assert (row["slug"], row["method_id"]) == (
        "registered-command-quick", "command",
    )
    assert json.loads(row["method_config"])["command"] == (
        "python3 -m pytest -q"
    )
    merge_row = test_db.execute(
        "SELECT c.method_id, c.method_config "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "WHERE p.slug='pre-merge-verification'"
    ).fetchone()
    assert merge_row["method_id"] == "command"
    assert json.loads(merge_row["method_config"])[
        "execution_point"
    ] == "post_rebase_merge"

    first_state = _cutover_state(test_db)
    apply(test_db)
    invariants(test_db)

    assert _cutover_state(test_db) == first_state

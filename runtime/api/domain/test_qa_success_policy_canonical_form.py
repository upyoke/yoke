"""A QA success policy is stored and read in one structured form."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain import qa_cli_requirement_insert
from yoke_core.domain.deployment_requirement_snapshot_format import (
    REQUIREMENT_FIELDS,
    semantic_row,
)
from yoke_core.domain.handlers import qa_requirement_insert
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.qa_requirement_config_update import apply_requirement_update
from yoke_core.domain.qa_requirement_policy_validation import (
    ALL_PASS_POLICY,
    canonical_success_policy,
    decode_success_policy,
)


ENTRY_NAME = "0085_qa_success_policy_named_form"
CREATED_AT = datetime(2026, 10, 18, tzinfo=timezone.utc)
ROW = {"qa_kind": "smoke", "qa_phase": "post_deploy", "success_policy": "all-pass"}


def _entry() -> Any:
    directory = history_dir(migration_history_package)
    record = next(
        entry for entry in ordered_entries(directory) if entry.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{record.name}.py", record.name)


def test_the_all_pass_name_is_stored_as_its_structured_form() -> None:
    assert canonical_success_policy("all-pass") == ALL_PASS_POLICY
    assert canonical_success_policy({"id": "all-pass", "params": {}}) == (
        ALL_PASS_POLICY
    )
    assert canonical_success_policy(None) is None
    assert canonical_success_policy("") is None
    assert decode_success_policy(ALL_PASS_POLICY) == {"id": "all-pass", "params": {}}


def test_an_unreadable_stored_policy_names_the_requirement_and_its_fix() -> None:
    with pytest.raises(ValueError) as refusal:
        decode_success_policy("all-pass", requirement_id=46123)

    message = str(refusal.value)
    assert message.startswith("qa_success_policy_unreadable:")
    assert "--requirement-id 46123 --field success_policy --value all-pass" in message
    assert "Expecting value" not in message


def test_snapshot_rows_decode_the_stored_policy() -> None:
    row = {"id": 7, "success_policy": ALL_PASS_POLICY}

    decoded = semantic_row(row, REQUIREMENT_FIELDS)

    assert decoded["success_policy"] == {"id": "all-pass", "params": {}}


def test_both_insert_paths_store_the_structured_form(test_db: Any) -> None:
    dispatcher = qa_requirement_insert.insert_params(
        qa_requirement_insert.RequirementSubject.for_item(1), ROW, CREATED_AT
    )
    operator = qa_cli_requirement_insert.insert_params(
        conn=test_db,
        item_id=1,
        epic_id=None,
        task_num=None,
        deployment_run_id=None,
        row=ROW,
        created_at=CREATED_AT,
    )

    assert ALL_PASS_POLICY in dispatcher
    assert "all-pass" not in dispatcher
    assert ALL_PASS_POLICY in operator
    assert "all-pass" not in operator


def test_requirement_update_stores_the_structured_form_and_refuses_text(
    test_db: Any,
) -> None:
    insert_item(test_db, id=9651, project_sequence=9651, status="implementing")
    requirement = insert_qa_requirement(test_db, item_id=9651)
    test_db.commit()

    updated = apply_requirement_update(
        test_db, requirement["id"], "success_policy", "all-pass"
    )
    refused = apply_requirement_update(
        test_db, requirement["id"], "success_policy", "Workflow completes"
    )

    assert updated.ok, updated.message
    stored = test_db.execute(
        "SELECT success_policy FROM qa_requirements WHERE id=%s", (requirement["id"],)
    ).fetchone()[0]
    assert stored == ALL_PASS_POLICY
    assert not refused.ok
    assert refused.error_code == "payload_invalid"
    assert "qa_success_policy_invalid" in refused.message


def test_history_entry_rewrites_stored_policy_names_once() -> None:
    entry = _entry()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE qa_requirements (id INTEGER, success_policy TEXT)")
    conn.executemany(
        "INSERT INTO qa_requirements VALUES (?, ?)",
        [
            (1, "all-pass"),
            (2, "all_pass"),
            (3, '{"type":"deterministic","criteria":"verdict_pass"}'),
            (4, None),
        ],
    )

    entry.apply(conn)
    entry.apply(conn)
    entry.invariants(conn)

    rows = dict(conn.execute("SELECT id, success_policy FROM qa_requirements"))
    assert rows == {
        1: ALL_PASS_POLICY,
        2: ALL_PASS_POLICY,
        3: '{"type":"deterministic","criteria":"verdict_pass"}',
        4: None,
    }
    assert entry.STRUCTURED_FORM == ALL_PASS_POLICY

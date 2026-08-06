"""Function-event evidence regressions for claim-boundary audit."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain.check_claim_boundary_audit_function_evidence import (
    FunctionAuditMetadata,
    target_item_id,
)
from yoke_core.domain.yoke_function_dispatch_claim_evidence import (
    CLAIM_VERIFICATION_ALLOWED,
    CLAIM_VERIFICATION_PHASE,
    WORK_CLAIM_AUTHORITY,
)
from runtime.api.engines.test_doctor_hc_claim_boundary_audit import (
    _add_claim,
    _add_event,
    _add_session,
    _p,
    _run,
    _sid,
)
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[dict]:
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield {"conn": conn}
        finally:
            conn.close()


def _add_harness_preview(conn, caller: str, item_id: int) -> None:
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_name": "HarnessToolCallCompleted",
        "session_id": caller,
        "context": {"detail": {"tool_response_preview": json.dumps({
            "success": True,
            "function": "items.structured_field.replace",
            "result": {"item_id": item_id},
        })}},
    }
    p = _p(conn)
    conn.execute(
        "INSERT INTO events (event_id, source_type, session_id, severity,"
        " event_kind, event_type, event_name, envelope, anomaly_flags,"
        " tool_name, created_at)"
        f" VALUES ({p}, 'agent', {p}, 'INFO', 'system', 'tool_call',"
        f" 'HarnessToolCallCompleted', {p}, 'unattributed', 'Bash',"
        " '2026-05-17T12:00:01Z')",
        (envelope["event_id"], caller, json.dumps(envelope)),
    )
    conn.commit()


def test_typed_target_item_wins_over_divergent_event_index(env):
    conn = env["conn"]
    caller, indexed_holder = _sid("v"), _sid("w")
    _add_session(conn, caller)
    _add_session(conn, indexed_holder)
    _add_claim(conn, caller, 918)
    _add_claim(conn, indexed_holder, 919)
    _add_event(
        conn,
        "YokeFunctionCalled",
        caller,
        919,
        {
            "function": "items.structured_field.replace",
            "target": {"kind": "item", "item_id": 918},
        },
    )
    _add_harness_preview(conn, caller, 918)

    assert _run(conn).results[0].result == "PASS"


def test_target_item_identity_requires_a_bare_integer():
    metadata = FunctionAuditMetadata(("db_write",), "item")

    assert target_item_id(
        {"target": {"kind": "item", "item_id": 918}}, metadata, None,
    ) == 918
    assert target_item_id(
        {"target": {"kind": "item", "item_id": "ALPHA-918"}}, metadata, None,
    ) is None


def test_pre_handler_evidence_survives_terminal_claim_release(env):
    conn = env["conn"]
    caller = _sid("x")
    _add_session(conn, caller)
    _add_claim(
        conn,
        caller,
        920,
        claimed_at="2026-05-17T11:00:00Z",
        released_at="2026-05-17T11:59:59Z",
    )
    _add_event(
        conn,
        "YokeFunctionCalled",
        caller,
        920,
        {
            "function": "lifecycle.transition.execute",
            "target": {"kind": "item", "item_id": 920},
            "side_effects": ["emit_item_status_changed"],
            "claim_required_kind": "item",
            "claim_verification": {
                "phase": CLAIM_VERIFICATION_PHASE,
                "required_kind": "item",
                "decision": CLAIM_VERIFICATION_ALLOWED,
                "caller_session_id": caller,
                "target_kind": "item",
                "target_item_id": 920,
                "authority": WORK_CLAIM_AUTHORITY,
                "claim_id": 12,
                "holder_session_id": caller,
            },
        },
    )

    assert _run(conn).results[0].result == "PASS"


def test_registry_side_effect_metadata_excludes_section_read(env):
    conn = env["conn"]
    caller = _sid("y")
    _add_session(conn, caller)
    _add_event(
        conn,
        "YokeFunctionCalled",
        caller,
        921,
        {
            "function": "items.section.get",
            "target": {"kind": "item", "item_id": 921},
        },
    )

    assert _run(conn).results[0].result == "PASS"

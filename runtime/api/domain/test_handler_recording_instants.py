"""Native generated clocks survive SQL recording and exact liveness cutoffs."""

import json
from contextlib import nullcontext
from datetime import timedelta
from uuid import uuid4

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    materialize_installer_campaign,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import machine_qa_case_evidence as evidence
from yoke_core.domain.handlers import merge_engine_post_rebase_ci as ci
from yoke_core.domain.machine_qa_execution import MachineCaseResult
from yoke_core.domain.qa_artifact_handle import s3_handle
from yoke_core.domain.qa_case_execution_context import get_case_execution_context
from yoke_core.hooks import sessions_inventory as inventory


MOMENT = parse_instant("2026-11-01T05:29:59.123456+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]


@pytest.mark.parametrize("zone", ZONES)
def test_stale_inventory_uses_exact_native_heartbeat_and_tool_cutoffs(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(inventory, "utc_now", lambda: MOMENT)
    cutoff = MOMENT - timedelta(minutes=60)
    before = cutoff - timedelta(microseconds=1)
    ids = [str(uuid4()) for _ in range(4)]
    for session, heartbeat, tool in zip(
        ids, [before, cutoff, before, before], [None, None, before, cutoff]
    ):
        test_db.execute(
            "INSERT INTO harness_sessions "
            "(session_id,executor,provider,model,workspace,offered_at,"
            "last_heartbeat,last_tool_call_at) "
            "VALUES (%s,'codex','openai','clock-test','/tmp',%s,%s,%s)",
            (session, MOMENT, heartbeat, tool),
        )
    rows = inventory.cmd_stale(test_db).splitlines()
    selected = {row.split("|")[0] for row in rows}
    assert ids[0] in selected and ids[2] in selected
    assert ids[1] not in selected and ids[3] not in selected
    assert all(
        row.endswith(format_instant(before)) for row in rows if row.split("|")[0] in ids
    )


@pytest.mark.parametrize("zone", ZONES)
def test_machine_capture_and_artifact_share_native_recording_fact(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(evidence, "utc_now", lambda: MOMENT)
    materialized = materialize_installer_campaign(test_db, item_id=42)
    requirement = next(
        int(row["id"])
        for row in materialized
        if row["plan_case_key"] == "default-add-yoke-to-my-path"
    )
    case = get_case_execution_context(test_db, requirement_id=requirement)
    monkeypatch.setattr(
        "yoke_core.domain.qa_artifact_storage.store_artifact_bytes",
        lambda *_args, **_kwargs: s3_handle(
            "test-artifacts", "native-clock/machine-evidence.json", "application/json"
        ),
    )
    opaque = {"machine": "test-host", "observed_at": "unparsed-capture", "steps": []}
    result = MachineCaseResult(
        case_outcome="needs_review",
        verdict="pending",
        capture_degraded_reason=None,
        evidence=opaque,
    )
    recorded = evidence.record_machine_case_result(
        test_db, case=case, result=result, duration_ms=12
    )
    row = test_db.execute(
        "SELECT started_at,completed_at,created_at,raw_result FROM qa_runs WHERE id=%s",
        (recorded["run_id"],),
    ).fetchone()
    assert tuple(row)[:3] == (MOMENT, MOMENT, MOMENT)
    assert json.loads(row["raw_result"])["evidence"] == opaque
    artifact = test_db.execute(
        "SELECT created_at,pg_typeof(created_at)::text FROM qa_artifacts WHERE qa_run_id=%s",
        (recorded["run_id"],),
    ).fetchone()
    assert artifact == (MOMENT, "timestamp with time zone")


@pytest.mark.parametrize("zone", ZONES)
def test_merge_ci_requirement_and_run_retain_native_microseconds(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(ci, "utc_now", lambda: MOMENT)
    monkeypatch.setattr(ci, "_connect_rw", lambda: nullcontext(test_db))
    item = 42
    insert_item(test_db, id=item, source=str(seed_human_actor(test_db)))
    request = FunctionCallRequest(
        function="merge.tests.record_post_rebase_ci_run",
        actor=ActorContext(actor_id=None, session_id="clock-test"),
        target=TargetRef(kind="item", item_id=item),
        payload={
            "scope": "full",
            "command": "python3 verify_tree.py",
            "workflow": "ci.yml",
            "verdict": "pass",
            "raw_result": json.dumps({"verification_tree": {"head_sha": "a" * 40}}),
        },
    )
    outcome = ci.handle_record_post_rebase_ci_run(request)
    assert outcome.primary_success, outcome.error
    row = test_db.execute(
        "SELECT r.started_at,r.completed_at,r.created_at,q.created_at "
        "FROM qa_runs r JOIN qa_requirements q ON q.id=r.qa_requirement_id WHERE r.id=%s",
        (outcome.result_payload["qa_run_id"],),
    ).fetchone()
    assert row == (MOMENT, MOMENT, MOMENT, MOMENT)

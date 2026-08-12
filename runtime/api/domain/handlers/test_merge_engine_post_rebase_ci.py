"""Claim-free merge-gate CI evidence recording."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import merge_engine_internal_ops as ops
from yoke_core.domain.handlers import merge_engine_post_rebase_ci as ci


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _item_envelope(function, *, item_id, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-merge-ci"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


def test_record_creates_ci_requirement_and_covering_pass(db):
    item_id = 9501
    head_sha = "a" * 40
    conn = connect_test_db(db)
    try:
        insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
        from yoke_core.domain.qa_command_plan_registration import (
            ensure_registered_command_plan,
        )

        ensure_registered_command_plan(
            conn,
            project_id=1,
            project="yoke",
            scope="full",
            command="python3 verify_tree.py",
        )
    finally:
        conn.close()

    raw = json.dumps(
        {
            "verification_tree": {"head_sha": head_sha, "root": "/tmp/x"},
            "ci_run_id": "99",
            "run_url": "https://github.com/acme/x/actions/runs/99",
            "ci_conclusion": "success",
        },
        sort_keys=True,
    )
    outcome = ci.handle_record_post_rebase_ci_run(
        _item_envelope(
            "merge.tests.record_post_rebase_ci_run",
            item_id=item_id,
            payload={
                "scope": "full",
                "command": "python3 verify_tree.py",
                "workflow": "ci.yml",
                "verdict": "pass",
                "raw_result": raw,
                "duration_ms": 1200,
            },
        )
    )
    assert outcome.primary_success, outcome.error
    ci.RecordPostRebaseCiRunResponse(**outcome.result_payload)
    run_id = outcome.result_payload["qa_run_id"]
    requirement_id = outcome.result_payload["requirement_id"]

    covering = ops.handle_post_rebase_requirement(
        _item_envelope("merge.tests.post_rebase_requirement", item_id=item_id)
    )
    assert covering.primary_success, covering.error
    runs = covering.result_payload["covering_runs"]
    assert any(
        r["run_id"] == run_id
        and r["head_sha"] == head_sha
        and r["runner_id"] == "ci_run"
        for r in runs
    )

    # Idempotent requirement reuse on a second record.
    again = ci.handle_record_post_rebase_ci_run(
        _item_envelope(
            "merge.tests.record_post_rebase_ci_run",
            item_id=item_id,
            payload={
                "scope": "full",
                "command": "python3 verify_tree.py",
                "workflow": "ci.yml",
                "verdict": "fail",
                "raw_result": raw,
            },
        )
    )
    assert again.primary_success, again.error
    assert again.result_payload["requirement_id"] == requirement_id


def test_record_requires_item_target(db):
    outcome = ci.handle_record_post_rebase_ci_run(
        FunctionCallRequest(
            function="merge.tests.record_post_rebase_ci_run",
            actor=ActorContext(actor_id=None, session_id="s-merge-ci"),
            target=TargetRef(kind="global"),
            payload={
                "scope": "full",
                "verdict": "pass",
                "raw_result": "{}",
            },
        )
    )
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "target_invalid"

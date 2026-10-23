"""Routine activity reads omit case bodies without losing their outcomes."""

from contextlib import contextmanager
import json
from unittest.mock import patch

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from runtime.api.fixtures.pg_testdb import test_database
from yoke_cli.commands.adapters import qa_catalog
from yoke_cli.transport.output_limit import REPLY_LIMIT_BYTES
from yoke_cli.transport.public_ref_display import emit_response
from yoke_contracts.api.function_call import (
    ActorContext, FunctionCallRequest, FunctionCallResponse, TargetRef,
)
from yoke_core.domain.handlers.qa_catalog_reads import handle_activity_list


def test_large_case_summary_renders_and_full_preserves_bodies(capsys):
    instructions = "Check the recorded behavior.\n" * 1000
    target = json.dumps({"description": "large target" * 3000})
    with test_database() as conn:
        insert_item(conn, id=4890, title="Activity detail")
        requirement = insert_qa_requirement(
            conn, item_id=4890, method_id="terminal-inspection",
            plan_case_key="inspect", instructions=instructions,
            execution_target_json=target,
        )
        run = insert_qa_run(
            conn, qa_requirement_id=int(requirement["id"]),
            performed_by="host_control", verdict="pass",
        )
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id, artifact_type, created_at) "
            "VALUES (%s, 'terminal_screenshot', %s)",
            (int(run["id"]), "2026-07-29T00:00:00Z"),
        )
        conn.commit()

        @contextmanager
        def connected():
            yield conn

        results = {}
        for detail in (None, "full"):
            payload = {"project": "yoke", "item_ids": [4890], "limit": 1}
            if detail:
                payload["detail"] = detail
            request = FunctionCallRequest(
                function="qa.activity.list",
                actor=ActorContext(actor_id="op", session_id="s-1"),
                target=TargetRef(kind="global"), payload=payload,
            )
            with patch("yoke_core.domain.db_helpers.connect", connected):
                outcome = handle_activity_list(request)
            assert outcome.primary_success, outcome.error
            results[detail] = outcome.result_payload

    summary = results[None]
    row = summary["rows"][0]
    assert not {"instructions", "artifacts", "execution_target_json"} & row.keys()
    assert row["requirement_id"] == int(requirement["id"])
    assert row["run_id"] == int(run["id"])
    assert row["case_key"] == "inspect"
    assert row["outcome"] == "passed"
    assert row["evidence_count"] == 1
    assert row["happened_at"]
    response = FunctionCallResponse(
        success=True, function="qa.activity.list", version="v1", result=summary,
    )
    assert emit_response(response, json_mode=False) == 0
    printed = capsys.readouterr()
    assert not printed.err
    assert len(printed.out.encode("utf-8")) < REPLY_LIMIT_BYTES
    full = results["full"]["rows"][0]
    assert full["instructions"] == instructions
    assert full["execution_target_json"] == json.loads(target)
    assert len(full["artifacts"]) == 1
    assert {key: value for key, value in full.items() if key in row} == row


@pytest.mark.parametrize("flags, detail", [([], "summary"), (["--full"], "full")])
def test_activity_cli_passes_read_detail(flags, detail):
    with patch.object(qa_catalog, "dispatch_and_emit", return_value=0) as dispatch:
        assert qa_catalog.qa_activity_list(["--project", "example", *flags]) == 0
    assert dispatch.call_args.kwargs["payload"] == {
        "project": "example", "limit": 100, "detail": detail,
    }

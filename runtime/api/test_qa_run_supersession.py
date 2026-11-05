"""Late CI writes preserve abandoned runs and their evidence."""

import base64
import json
from unittest.mock import patch

import pytest

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.handlers import qa_browser_writes as writes
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.api_qa_browser_function_test_support import (
    _request,
    _seed_browser_requirement,
)


def request(function, run_id, **payload):
    return _request(
        function,
        TargetRef(kind="qa_requirement", qa_requirement_id=10),
        payload={"run_id": run_id, **payload},
    )


def add(verdict=None, raw="{}"):
    result = writes.handle_qa_run_add(
        request("qa.run.add", 0, performed_by="ci_run", verdict=verdict, raw_result=raw)
    )
    assert result.primary_success, result.error
    return result.result_payload["qa_run_id"]


def snapshot(conn, run_id):
    return tuple(
        conn.execute("SELECT * FROM qa_runs WHERE id=%s", (run_id,)).fetchone()
    )


@pytest.mark.parametrize("late_verdict", ["pass", "fail", "error"])
def test_replaced_error_ignores_completion_and_artifact(late_verdict):
    with test_database() as conn, patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        _seed_browser_requirement(conn)
        run_id = add("error", json.dumps({"replacement_ci_run_id": 900}))
        add()
        before = snapshot(conn, run_id)
        with patch(
            "yoke_core.domain.handlers.qa_artifact_add._store_inline_bytes"
        ) as store:
            artifact = writes.handle_qa_artifact_add(
                request(
                    "qa.artifact.add",
                    run_id,
                    artifact_type="command_output",
                    content_base64=base64.b64encode(b"obsolete output").decode(),
                    filename="output.txt",
                )
            )
        assert artifact.primary_success
        assert artifact.result_payload["already_settled"]
        assert "qa_artifact_id" not in artifact.result_payload
        store.assert_not_called()
        with patch("yoke_core.domain.qa_events.emit_qa_run_event") as emit:
            result = writes.handle_qa_run_complete(
                request(
                    "qa.run.complete",
                    run_id,
                    verdict=late_verdict,
                    raw_result='{"late":true}',
                    duration_ms=42,
                )
            )
        assert result.primary_success
        assert result.result_payload == {
            "qa_run_id": run_id,
            "already_settled": True,
            "verdict": "error",
            "ignored_verdict": late_verdict,
        }
        emit.assert_not_called()
        assert snapshot(conn, run_id) == before
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id=%s", (run_id,)
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "verdict,raw,newer",
    [
        ("error", '{"replacement_ci_run_id":900}', False),
        ("error", "{}", True),
        ("error", "invalid json", True),
        ("error", "[]", True),
        ("pass", '{"replacement_ci_run_id":900}', True),
        ("fail", '{"replacement_ci_run_id":900}', True),
    ],
)
def test_other_settled_runs_retain_immutability(verdict, raw, newer):
    with test_database() as conn, patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        _seed_browser_requirement(conn)
        run_id = add(verdict, raw)
        if newer:
            add()
        before = snapshot(conn, run_id)
        with pytest.raises(Exception, match="immutable once verdict is set"):
            writes.handle_qa_run_complete(
                request(
                    "qa.run.complete",
                    run_id,
                    verdict="error",
                    raw_result='{"late":true}',
                )
            )
        assert snapshot(conn, run_id) == before


def test_newer_run_for_another_requirement_does_not_qualify():
    from runtime.api.fixtures.backlog_inserts import insert_qa_requirement

    with test_database() as conn, patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        _seed_browser_requirement(conn)
        run_id = add("error", '{"replacement_ci_run_id":900}')
        insert_qa_requirement(
            conn,
            id=11,
            item_id=42,
            qa_kind="plan_case",
            qa_phase="verification",
            blocking_mode="blocking",
            success_policy="",
        )
        conn.commit()
        other = _request(
            "qa.run.add",
            TargetRef(kind="qa_requirement", qa_requirement_id=11),
            payload={"performed_by": "ci_run"},
        )
        assert writes.handle_qa_run_add(other).primary_success
        with pytest.raises(Exception, match="immutable once verdict is set"):
            writes.handle_qa_run_complete(
                request("qa.run.complete", run_id, verdict="pass")
            )

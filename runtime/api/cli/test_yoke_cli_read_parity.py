"""CLI guess routing, exact-read payloads, and metadata-only QA output."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.commands.registry import resolve
from yoke_cli.conceptual_cli_names import conceptual_cli_hint
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, FunctionCallResponse, TargetRef
from yoke_core.domain.db_read_column_hints import column_hint
from yoke_core.domain.handlers.qa_artifact_metadata import handle_artifact_get
from yoke_core.domain.handlers.decision_request_get import handle_decision_request_get
from yoke_core.domain.handlers.reads import handle_items_get


@pytest.mark.parametrize("tokens,function_id", [
    (["sessions", "get"], "sessions.list"),
    (["claims", "work", "list"], "claims.work.holder_list"),
    (["claims", "work-claim", "acquire"], "claims.work.acquire"),
    (["qa", "methods", "list"], "qa.method.list"),
    (["items", "progress-log", "get"], "items.progress_log.get"),
    (["projects", "environment", "list"], "projects.environment.list"),
])
def test_common_guesses_resolve(tokens, function_id):
    assert resolve(tokens)[1] == function_id


def test_say_inbox_explains_hook_delivery_and_exact_message_read():
    hint = conceptual_cli_hint(["say", "inbox"])
    assert "session hook" in hint
    assert "yoke messages get MESSAGE-ID" in hint


def _run(*argv):
    requests = []

    def dispatch(request):
        requests.append(request)
        return FunctionCallResponse(
            success=True, function=request.function, version=request.version,
            request_id=request.request_id, result={"environments": []},
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "read-parity-test"}):
        with patch("yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=dispatch):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = cli_main(list(argv))
    return code, requests


@pytest.mark.parametrize("argv,function_id,payload", [
    (("sessions", "get", "session-123"), "sessions.list", {"session_id": "session-123"}),
    (("qa", "plan", "get", "smoke", "--project", "demo"), "qa.plan.get", {"project": "demo", "plan_id": "smoke", "detail": "summary"}),
    (("qa", "plan", "get", "--plan-id", "12", "--project", "demo"), "qa.plan.get", {"project": "demo", "plan_id": 12, "detail": "summary"}),
    (("decision-requests", "get", "9"), "decision_requests.get", {"request_id": 9}),
    (("qa", "artifact", "get", "7", "--requirement-id", "4"), "qa.artifact.get", {"artifact_id": 7}),
    (("projects", "environment", "list", "--project", "demo"), "projects.environment.list", {"project": "demo"}),
])
def test_read_invocations_dispatch_expected_payload(argv, function_id, payload):
    code, requests = _run(*argv)
    assert code == 0
    assert requests[-1].function == function_id
    assert requests[-1].payload == payload


@pytest.mark.parametrize("args", [("--requirement-id", "4"), ("4",)])
def test_requirement_get_accepts_both_id_forms(args):
    code, requests = _run("qa", "requirement", "get", *args)
    assert code == 0
    assert requests[-1].target.qa_requirement_id == 4


def test_requirement_get_rejects_ambiguous_id():
    code, requests = _run("qa", "requirement", "get", "4", "--requirement-id", "5")
    assert code == 2
    assert requests == []


def test_progress_log_read_targets_only_the_item():
    code, requests = _run("items", "progress-log", "get", "DEMO-4")
    assert code == 0
    assert requests[-1].function == "items.progress_log.get"
    assert requests[-1].target.public_ref == "DEMO-4"


@pytest.mark.parametrize("argv", [
    ("sessions", "get"), ("decision-requests", "get"),
    ("items", "progress-log", "get"), ("projects", "environment", "list"),
    ("qa", "artifact", "get"),
])
def test_new_read_help_has_a_usage_line(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        assert cli_main([*argv, "--help"]) == 0
    assert "usage:" in out.getvalue().lower()


def test_items_get_refuses_unknown_field_before_querying():
    outcome = handle_items_get(FunctionCallRequest(
        function="items.get.run", actor=ActorContext(actor_id="1", session_id="read-test"),
        target=TargetRef(kind="item", item_id=1), payload={"fields": ["missing_field"]},
    ))
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "missing_field" in outcome.error.message


def test_artifact_get_returns_metadata_without_download_details():
    conn = MagicMock()
    conn.__enter__.return_value = conn
    row = {
        "id": 7, "qa_run_id": 3, "artifact_type": "screenshot",
        "content_type": "image/png", "metadata": "{}", "created_at": "2026-01-01",
    }
    with patch("yoke_core.domain.db_helpers.connect", return_value=conn):
        with patch("yoke_core.domain.db_helpers.query_one", return_value=row):
            outcome = handle_artifact_get(FunctionCallRequest(
                function="qa.artifact.get",
                actor=ActorContext(actor_id="1", session_id="read-test"),
                target=TargetRef(kind="qa_requirement", qa_requirement_id=4),
                payload={"artifact_id": 7},
            ))
    assert outcome.primary_success
    assert outcome.result_payload["artifact"]["artifact_type"] == "screenshot"
    assert "download_url" not in outcome.result_payload["artifact"]
    assert "artifact_handle" not in outcome.result_payload["artifact"]


def test_decision_get_hides_request_from_unrelated_actor():
    conn = MagicMock()
    conn.__enter__.return_value = conn
    with patch("yoke_core.domain.db_helpers.connect", return_value=conn):
        with patch("yoke_core.domain.decision_request_rows.request_row", return_value={
            "id": 8, "decisions": [], "originator_actor_id": 1,
        }):
            with patch("yoke_core.domain.decision_request_authority.authority_reason", return_value=None):
                outcome = handle_decision_request_get(FunctionCallRequest(
                    function="decision_requests.get",
                    actor=ActorContext(actor_id="2", session_id="read-test"),
                    target=TargetRef(kind="global"), payload={"request_id": 8},
                ))
    assert not outcome.primary_success
    assert outcome.error.code == "not_found"


def test_schema_hints_name_structured_text_storage():
    assert column_hint("work_claims", "scope", "text") == "scope text (JSON document stored as text)"
    assert column_hint("events", "created_at", "text") == "created_at text (timestamp stored as text)"

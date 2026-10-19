"""QA method reads use the session project when the caller omits one."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.session_holdings import insert_session
from yoke_core.domain.handlers.qa_catalog_reads import (
    handle_method_get,
    handle_method_list,
)


def _request(function: str, payload: dict, session_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id=session_id),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_omitted_project_uses_the_session_project(test_db, monkeypatch):
    insert_session(test_db, "method-session-project")
    seen: dict[str, str] = {}

    def fake_list(_conn, *, project=None):
        seen["project"] = project
        return []

    monkeypatch.setattr(
        "yoke_core.domain.qa_catalog_reads.list_methods",
        fake_list,
    )
    outcome = handle_method_list(
        _request("qa.method.list", {}, "method-session-project")
    )
    assert outcome.primary_success
    assert seen["project"] == "1"


def test_explicit_project_wins(test_db, monkeypatch):
    insert_session(test_db, "method-explicit-project")
    seen: dict[str, str] = {}

    def fake_get(_conn, *, method_id, project=None):
        seen["project"] = project
        seen["method_id"] = method_id
        return {"id": method_id}

    monkeypatch.setattr(
        "yoke_core.domain.qa_catalog_reads.get_method",
        fake_get,
    )
    outcome = handle_method_get(
        _request(
            "qa.method.get",
            {"method_id": "command", "project": "yoke"},
            "method-explicit-project",
        )
    )
    assert outcome.primary_success
    assert seen == {"project": "yoke", "method_id": "command"}


def test_session_without_a_project_names_the_flag(test_db, monkeypatch):
    insert_session(test_db, "method-no-project")

    class _OrgSession:
        project_id = None

    monkeypatch.setattr(
        "yoke_core.domain.sessions_identity_read.resolve_session_identity",
        lambda _conn, _session_id: _OrgSession(),
    )
    outcome = handle_method_list(_request("qa.method.list", {}, "method-no-project"))
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
    assert "project_required" in outcome.error.message
    assert "--project" in outcome.error.message

"""A denied subagent call keeps its agent type on ``HarnessToolCallDenied``.

The relay's client subset hands the agent type back on its denial audit,
the denial-audit route forwards it, and ``emit_denial_event`` records it
as the event's ``agent``. Server-side guards and route refusals read the
same ``agent_type`` the relay merged into the payload or request.
"""

from __future__ import annotations

import json
from unittest import mock

from runtime.harness.test_hook_local_subset_denial_telemetry import (
    dirty_repo as dirty_repo,
)
from runtime.harness.test_hook_project_scope import project_map as project_map

from yoke_core.api.routes.hooks import HookEvaluateRequest, _refuse_conversation_shaped
from yoke_core.api.routes.hooks_denial_audit import (
    HookDenialAuditRequest,
    post_hooks_denial_audit,
)
from yoke_core.domain import lint_pipe_to_truncator
from yoke_core.hooks import denial
from yoke_harness.hooks import local_subset
from yoke_harness.hooks.deadline import start_hook_deadline

AGENT = "yoke-qa-walker"


class _FakeHttpRequest:
    pass


def _recorded_agent(**kwargs) -> object:
    with (
        mock.patch.object(denial, "_close_denied_call"),
        mock.patch("yoke_core.domain.emit_event.emit") as emit,
    ):
        denial.emit_denial_event(**kwargs)
    emit.assert_called_once()
    return emit.call_args.args[0].agent


def test_relay_deny_with_agent_type_records_that_agent(dirty_repo) -> None:
    payload = {
        "session_id": "sid-parent",
        "tool_name": "Bash",
        "tool_use_id": "tu-sub-1",
        "cwd": str(dirty_repo),
        "tool_input": {"command": "git reset --hard"},
    }
    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        json.dumps(payload),
        "claude",
        AGENT,
        start_hook_deadline(),
        lint_config_snapshot={},
    )
    assert result.denied is True
    assert result.denial_audit["agent_type"] == AGENT

    with (
        mock.patch("yoke_core.api.routes.hooks_denial_audit.require_auth_context"),
        mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical,
    ):
        post_hooks_denial_audit(
            _FakeHttpRequest(), HookDenialAuditRequest(**result.denial_audit)
        )
    forwarded = canonical.call_args.kwargs
    assert forwarded["agent"] == AGENT
    assert _recorded_agent(**forwarded) == AGENT


def test_denial_without_agent_records_no_agent() -> None:
    assert not _recorded_agent(hook="h", check_id="c", reason="r")


def test_route_refusal_records_the_request_agent_type() -> None:
    request = HookEvaluateRequest(
        event_name="PreToolUse",
        stdin=json.dumps({}),
        agent_type=AGENT,
        execution_provenance={"source_sha": "clientsha1234"},
    )
    with mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical:
        assert _refuse_conversation_shaped(request) is not None
    assert canonical.call_args.kwargs["agent"] == AGENT


def test_server_side_guard_denial_reads_payload_agent_type() -> None:
    payload = {"session_id": "sid-parent", "agent_type": AGENT}
    with mock.patch("yoke_core.hooks.telemetry.emit_denial_event") as canonical:
        lint_pipe_to_truncator._emit_audit_event(payload, "BLOCKED", "deny", "denied")
    assert canonical.call_args.kwargs["agent"] == AGENT

"""Coverage for the pre-dispatch hooks-evaluate route refusals' denial telemetry.

``_refuse_conversation_shaped`` and ``_authorize_scope`` return
``outcome="denied"`` before ``evaluate_remote``/``run_event`` ever runs, so
no guard module gets a chance to call ``emit_denial_event`` — these two
refusal shapes used to leave no durable ``HarnessToolCallDenied`` row.
"""

from __future__ import annotations

from fastapi import BackgroundTasks
import json
from unittest import mock

from yoke_core.api.routes.hooks import (
    HookEvaluateRequest,
    _authorize_scope,
    _guard_revision_skew_reason,
    _refuse_conversation_shaped,
    post_hooks_evaluate,
)
from yoke_core.api.routes.hooks_denial_audit import (
    HookDenialAuditRequest,
    post_hooks_denial_audit,
)
from yoke_core.hooks.denial import build_denial_payload
from yoke_core.hooks.remote_entry import RemoteEvaluation
from yoke_core.api.http_auth import HttpAuthContext
from yoke_core.domain.session_scope_identity import HookScopeDecision


def _request(stdin: dict, **overrides) -> HookEvaluateRequest:
    overrides.setdefault("execution_provenance", {"source_sha": "clientsha1234"})
    return HookEvaluateRequest(
        event_name="PreToolUse",
        stdin=json.dumps(stdin),
        **overrides,
    )


def test_missing_session_id_denies_and_emits() -> None:
    request = _request({})
    with mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical:
        response = _refuse_conversation_shaped(request)
    assert response is not None
    canonical.assert_called_once()
    kwargs = canonical.call_args.kwargs
    assert kwargs["check_id"] == "conversation_shaped_session"
    assert kwargs["guard_key"] == "conversation_shaped_session"
    assert kwargs["mode"] == "deny"
    assert kwargs["client_revision"] == "clientsha1234"


def test_conversation_shaped_session_id_denies_and_emits() -> None:
    request = _request(
        {
            "session_id": "conv-1",
            "conversation_id": "conv-1",
            "tool_use_id": "tu-9",
        }
    )
    with mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical:
        response = _refuse_conversation_shaped(request)
    assert response is not None
    canonical.assert_called_once()
    kwargs = canonical.call_args.kwargs
    assert kwargs["check_id"] == "conversation_shaped_session"
    assert kwargs["tool_use_id"] == "tu-9"


def test_stamped_identity_allows_without_emitting() -> None:
    # A stamped id is not re-litigated by shape: for a self-mapped Cursor
    # session the canonical id equals the conversation alias beside it.
    request = _request(
        {
            "identity_stamped": True,
            "session_id": "sid-1",
            "conversation_id": "sid-1",
        }
    )
    with mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical:
        response = _refuse_conversation_shaped(request)
    assert response is None
    canonical.assert_not_called()


def test_a_stamp_without_an_identity_still_denies() -> None:
    """The stamp is a claim about a session id, not a substitute for one."""
    request = _request({"identity_stamped": True})
    with mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical:
        response = _refuse_conversation_shaped(request)
    assert response is not None
    canonical.assert_called_once()


def test_unbound_machine_credential_denies_and_emits() -> None:
    request = _request({"session_id": "sid-1"}, project_id=None)
    decision = HookScopeDecision(
        denial_code="machine_credential_required",
        reason="A machine-bound credential is required. Recovery: reconnect this machine with the installer.",
    )
    with (
        mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical,
        mock.patch(
            "yoke_core.api.routes.hooks.authorize_hook_request", return_value=decision
        ),
    ):
        authorized, response = _authorize_scope(HttpAuthContext(1, 1, "test"), request)
    assert response is not None
    assert authorized == decision
    canonical.assert_called_once()
    kwargs = canonical.call_args.kwargs
    assert kwargs["check_id"] == "machine_credential_required"
    assert kwargs["client_revision"] == "clientsha1234"
    assert decision.reason in kwargs["reason"]
    assert "Recovery: reconnect" in kwargs["reason"]


def test_actor_without_project_visibility_denies_and_emits() -> None:
    request = _request({"session_id": "sid-1"}, project_id=7)
    with (
        mock.patch(
            "yoke_core.domain.session_scope_identity.actor_visible_project_ids",
            return_value={1, 2},
        ),
        mock.patch("yoke_core.domain.db_helpers.connect") as connect,
        mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical,
    ):
        connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = None
        authorized, response = _authorize_scope(HttpAuthContext(1, 1, "test"), request)
    assert response is not None
    assert authorized.project_slug == ""
    canonical.assert_called_once()
    kwargs = canonical.call_args.kwargs
    assert kwargs["check_id"] == "HOOK_PROJECT_DENIED"
    assert kwargs["mode"] == "deny"


def test_guard_revision_skew_reason_names_both_revisions() -> None:
    request = _request({}, execution_provenance={"source_sha": "a" * 40})
    with mock.patch(
        "yoke_core.api.routes.hooks.collect_execution_provenance",
        return_value={"source_sha": "b" * 40},
    ):
        reason = _guard_revision_skew_reason(request)
    assert "bbbbbbbbbbbb" in reason
    assert "aaaaaaaaaaaa" in reason


def test_guard_revision_skew_reason_empty_when_revisions_match() -> None:
    request = _request({}, execution_provenance={"source_sha": "a" * 40})
    with mock.patch(
        "yoke_core.api.routes.hooks.collect_execution_provenance",
        return_value={"source_sha": "a" * 12},
    ):
        assert _guard_revision_skew_reason(request) == ""


def test_skew_annotation_preserves_the_actual_denying_check() -> None:
    request = _request(
        {"session_id": "sid-1", "identity_stamped": True},
        project_id=1,
        execution_provenance={"source_sha": "a" * 40},
    )
    denial = RemoteEvaluation(
        stdout="denied",
        exit_code=2,
        degraded=(),
        wait_ms=1,
        outcome="denied",
        denial_audit={
            "hook": "yoke_core.domain.turn_end_promised_work_gate",
            "check_id": "turn_end_promised_work_gate",
            "reason": "finish the claimed work",
        },
    )
    with (
        mock.patch(
            "yoke_core.api.routes.hooks.require_auth_context",
            return_value=HttpAuthContext(1, 1, "test"),
        ),
        mock.patch(
            "yoke_core.api.routes.hooks._authorize_scope",
            return_value=(
                HookScopeDecision(project_id=1, project_slug="example"),
                None,
            ),
        ),
        mock.patch("yoke_core.api.routes.hooks.evaluate_remote", return_value=denial),
        mock.patch(
            "yoke_core.api.routes.hooks.collect_execution_provenance",
            return_value={"source_sha": "b" * 40},
        ),
        mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical,
    ):
        response = post_hooks_evaluate(_FakeHttpRequest(), request, BackgroundTasks())
    assert response.status_code == 200
    kwargs = canonical.call_args.kwargs
    assert kwargs["check_id"] == "turn_end_promised_work_gate"
    assert kwargs["hook"] == "yoke_core.domain.turn_end_promised_work_gate"
    assert kwargs["reason"] == "finish the claimed work"
    assert "guard-revision skew" in kwargs["guard_version_skew"]


def test_guard_skew_is_a_separate_denial_payload_annotation() -> None:
    payload = build_denial_payload(
        hook="policy.module",
        check_id="claimed_work_gate",
        reason="finish the claimed work",
        client_revision="client-sha",
        server_revision="server-sha",
        guard_version_skew="revisions differ",
    )
    assert payload["check_id"] == "claimed_work_gate"
    assert payload["reason"] == "finish the claimed work"
    assert payload["guard_version_skew"] == {
        "reason": "revisions differ",
        "revision_pair": {"client": "client-sha", "server": "server-sha"},
    }
    assert "revision_pair" not in payload


class _FakeHttpRequest:
    pass


def test_post_hooks_denial_audit_calls_emit_denial_event() -> None:
    with (
        mock.patch("yoke_core.api.routes.hooks_denial_audit.require_auth_context"),
        mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical,
    ):
        response = post_hooks_denial_audit(
            _FakeHttpRequest(),
            HookDenialAuditRequest(
                hook="yoke_core.domain.lint_destructive_git",
                check_id="yoke_core.domain.lint_destructive_git",
                guard_key="yoke_core.domain.lint_destructive_git",
                mode="deny",
                reason="BLOCKED: destructive git",
                session_id="sid-local",
                tool_use_id="tu-local-1",
            ),
        )
    canonical.assert_called_once()
    kwargs = canonical.call_args.kwargs
    assert kwargs["hook"] == "yoke_core.domain.lint_destructive_git"
    assert kwargs["session_id"] == "sid-local"
    assert response.status_code == 200

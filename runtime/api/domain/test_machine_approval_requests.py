from __future__ import annotations

from yoke_core.domain import machine_approval_requests as approvals


def test_machine_approval_is_idempotent_org_admin_request(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        approvals,
        "list_subject_requests",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        approvals,
        "create_decision_request",
        lambda _conn, **kwargs: calls.append(kwargs) or (
            {"id": 7, "status": "pending"},
            True,
        ),
    )

    request, created = approvals.ensure_machine_approval(
        object(),
        auth_request_id="machine-request-abc",
        org_id=42,
        context={"code": "ABCD-EFGH", "machine": "test-mac"},
        originator_actor_id=9,
        session_id="session-1",
    )

    assert created is True
    assert request["id"] == 7
    assert calls[0]["kind"] == "machine_approval"
    assert calls[0]["subject_type"] == "machine_auth_request"
    assert calls[0]["subject_key"] == "machine-request-abc"
    assert calls[0]["role_authorities"][0] == approvals.RoleAuthority(
        "org", 42, "admin",
    )


def test_machine_approval_status_waits_then_returns_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        approvals,
        "list_subject_requests",
        lambda *_args: [{"status": "pending"}],
    )
    assert approvals.machine_approval_decision(
        object(), auth_request_id="machine-request-abc",
    ) is None

    monkeypatch.setattr(
        approvals,
        "list_subject_requests",
        lambda *_args: [{
            "status": "resolved",
            "resolution_action": "deny",
        }],
    )
    assert approvals.machine_approval_decision(
        object(), auth_request_id="machine-request-abc",
    ) == "deny"

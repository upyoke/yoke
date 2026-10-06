"""Shared request builder and resolver stub for ``github_actions.check_ci`` tests."""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


_RESOLVED = ProjectGithubAuth(
    project="yoke",
    repo="upyoke/yoke",
    token="ghs_test_token",
)


def _make_request(
    payload: Optional[Dict[str, Any]] = None,
    *,
    target_kind: str = "global",
    include_project: bool = True,
) -> FunctionCallRequest:
    if payload is None:
        payload = {"repo": "upyoke/yoke", "workflow": "ci.yml"}
    payload = dict(payload)
    if include_project:
        payload.setdefault("project", "yoke")
    return FunctionCallRequest(
        function="github_actions.check_ci",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


def stub_resolver(monkeypatch):
    """Resolve every project to the test App binding; return the handler module."""
    from yoke_core.domain.handlers import github_actions_check_ci as h

    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project, **kw: _RESOLVED,
    )
    return h

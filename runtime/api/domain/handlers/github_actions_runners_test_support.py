"""Shared request, runner, and authority fixtures for runner status tests."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth


_RESOLVED = ProjectGithubAuth(
    project="yoke",
    repo="upyoke/yoke",
    token="ghs_test_token",
    permissions={"administration": "read", "actions_variables": "read"},
)

def _make_request(
    payload: Optional[Dict[str, Any]] = None,
    *,
    target_kind: str = "global",
    include_project: bool = True,
) -> FunctionCallRequest:
    if payload is None:
        payload = {"repo": "upyoke/yoke"}
    payload = dict(payload)
    if include_project:
        payload.setdefault("project", "yoke")
    return FunctionCallRequest(
        function="github_actions.runners.status",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


@pytest.fixture(autouse=True)
def _auth_resolved(monkeypatch):
    calls = []

    def _resolve(project, **kwargs):
        calls.append((project, kwargs))
        return _RESOLVED

    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        _resolve,
    )
    return calls


def _runner(
    *,
    labels=("self-hosted", "Linux", "ARM64"),
    status="online",
    busy=False,
) -> Dict[str, Any]:
    return {
        "id": 7,
        "name": "build-runner",
        "status": status,
        "busy": busy,
        "labels": [{"name": label} for label in labels],
    }

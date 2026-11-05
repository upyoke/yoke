# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any, Dict, Optional

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)

from yoke_core.domain.handlers import github_actions_run

from yoke_core.domain.handlers.github_actions_run import (
    _classify,
    handle_run_get,
)

from yoke_core.domain.github_actions_run_stall import (
    CI_RUN_NEVER_STARTED_REASON,
    PENDING_ZERO_JOBS_STALL_SECONDS,
    PENDING_ZERO_JOBS_STALL_REASON,
    STALLED_DISPATCH_TOKEN,
    pending_run_message,
)

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
        payload = {"repo": "upyoke/yoke", "run_id": "123"}
    payload = dict(payload)
    if include_project:
        payload.setdefault("project", "yoke")
    return FunctionCallRequest(
        function="github_actions.wait_run",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )

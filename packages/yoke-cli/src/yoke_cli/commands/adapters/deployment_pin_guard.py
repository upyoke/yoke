"""Pre-dispatch check that a run will not regress a project's version pin.

The comparison itself runs here rather than server-side because both sides
of it live in the caller's checkout: the candidate ref and the
environment's pin branch are refs in the same repository, and the server
never sees that repository. The two facts the comparison needs from the
control plane — the project's pin declaration and the flow's target
environment — are read through the ordinary function-call transport, so
this adapter holds no database handle of its own. The guard is advisory in
the same sense the PreToolUse lints are: it refuses the ordinary path and
names the override.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Optional

from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.commands.deployment_pin import (
    RELEASE_PIN_CAPABILITY,
    PinRegressionError,
    assert_no_pin_regression,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef


def pin_regression_error(parsed: argparse.Namespace) -> Optional[str]:
    """Message describing a refused pin rollback, or None to proceed."""
    if getattr(parsed, "allow_pin_regression", False):
        return None
    session_id = getattr(parsed, "session_id", None)
    try:
        ensure_handlers_loaded()
        settings = _declared_pin_settings(parsed.project, session_id)
        if settings is None:
            return None
        source_ref = getattr(parsed, "source_ref", None)
        repo_path = getattr(parsed, "project_repo_path", None)
        retry_of = getattr(parsed, "retry_of", None)
        if retry_of:
            lineage = _retry_run_lineage(str(retry_of), session_id)
            if lineage:
                source_ref = lineage
            if not repo_path:
                from yoke_cli.config.checkout_context import (
                    resolve_repo_root_from_cwd,
                )
                repo_path = resolve_repo_root_from_cwd()
        assert_no_pin_regression(
            settings=settings,
            repo_path=repo_path,
            source_ref=source_ref,
            target_env=(
                parsed.target_env or _flow_target_env(parsed.flow, session_id)
            ),
        )
    except PinRegressionError as exc:
        return str(exc)
    except Exception:
        # A guard that cannot read its own inputs must not block a deploy;
        # the declaration is optional and any resolution failure here is a
        # missing capability or an unreachable control plane, not evidence
        # of a rollback.
        return None
    return None


def _retry_run_lineage(
    run_id: str, session_id: Optional[str]
) -> Optional[str]:
    """The immutable SHA pinned on a retry source run, if the plane has one."""
    response = call_dispatcher(
        function_id="deployment_runs.get",
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={},
        actor=build_actor(session_id=session_id),
    )
    if not response.success or not response.result:
        return None
    run = response.result.get("run") or {}
    lineage = run.get("release_lineage")
    if not isinstance(lineage, str):
        return None
    return lineage.strip() or None


def _declared_pin_settings(
    project: str, session_id: Optional[str]
) -> Optional[dict]:
    """The project's release-pin declaration, or None when it has none."""
    result = _read(
        "projects.capability_settings.get",
        {"project": project, "cap_type": RELEASE_PIN_CAPABILITY},
        session_id,
    )
    if result is None:
        return None
    settings = json.loads(str(result.get("settings_json") or "null"))
    if not isinstance(settings, dict) or not settings.get("pin_file"):
        return None
    return settings


def _flow_target_env(flow: str, session_id: Optional[str]) -> Optional[str]:
    """The environment a flow deploys to, when the caller named no override."""
    result = _read(
        "deployment_flows.get",
        {"flow_id": flow, "field": "target_env"},
        session_id,
    )
    return (result or {}).get("value") or None


def _read(
    function_id: str, payload: Dict[str, Any], session_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """A read call's result, or None when the control plane declined it."""
    response = call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(session_id=session_id),
    )
    return response.result if response.success else None


__all__ = ["pin_regression_error"]

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
        assert_no_pin_regression(
            settings=settings,
            repo_path=parsed.project_repo_path,
            source_ref=parsed.source_ref,
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

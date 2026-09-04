"""The gate-side write that makes a dispatched CI run survivable.

Called the moment a run id exists, from whichever gate dispatched it. It is
advisory in both directions: a run started outside any harness session has
nobody to wake and is not recorded, and a control plane that refuses the
write returns a warning rather than failing the run the caller is already
executing. What it buys is that the conclusion reaches the session even if
the process reading for it does not live to see it.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


def ambient_session_id() -> str:
    """The session this dispatch runs under, or empty when it has none."""
    try:
        from yoke_core.domain.session_ambient_identity import (
            resolve_ambient_session_id,
        )

        return str(resolve_ambient_session_id() or "").strip()
    except Exception:  # noqa: BLE001 - identity is evidence, never a failure
        return ""


def record_ci_run_wait(
    *,
    repo: str,
    run_id: str,
    kind: str,
    head_sha: str = "",
    continue_command: str = "",
    supersedes_run_id: str = "",
    dispatch: Callable[..., Any] = call_dispatcher,
    session_id: str | None = None,
) -> str:
    """Record that this session is owed ``run_id``'s verdict.

    ``supersedes_run_id`` names a run this one replaces, so a gate that
    re-dispatches drops the wait it is abandoning instead of leaving the
    session owed two verdicts for one gate.

    Returns ``""`` when the wait is recorded or there is no session to
    record one for, and a warning otherwise.
    """
    if not (session_id if session_id is not None else ambient_session_id()):
        return ""
    try:
        response = dispatch(
            function_id="session_ci_wait.record",
            target=TargetRef(kind="global"),
            payload={
                "repo": repo,
                "run_id": str(run_id),
                "kind": kind,
                "head_sha": head_sha,
                "continue_command": continue_command,
                "supersedes_run_id": supersedes_run_id,
            },
        )
    except Exception as exc:  # noqa: BLE001 - the run continues regardless
        return f"ci wait not recorded: {exc}"
    if getattr(response, "success", False):
        return ""
    error = getattr(response, "error", None)
    detail = str(getattr(error, "message", None) or "ci wait record failed")
    return f"ci wait not recorded: {detail}"


__all__ = ["ambient_session_id", "record_ci_run_wait"]

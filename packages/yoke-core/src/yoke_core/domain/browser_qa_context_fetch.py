"""The one requirement-scoped read a Browser case starts from.

``qa.browser_context.get`` answers with the named Browser method case, the
deployment the case is about, and — for a case hanging off a deployment run —
the commit that run was pinned to deliver. It goes through the Yoke
function-call dispatcher, so it works identically from a Yoke checkout on a
local-postgres env and from an external project over the https relay.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_contracts.api.function_call import ActorContext


def _fetch_browser_context(
    project: str,
    requirement_id: int,
    *,
    item_id: int | str | None = None,
    deployment_run_id: str | None = None,
    expected_branch: Optional[str] = None,
    actor: Optional[ActorContext] = None,
) -> Dict[str, Any]:
    """Fetch the scenario's DB context through the dispatcher.

    One requirement-scoped read: the named Browser method case plus (when
    ``expected_branch`` is given) the latest deployed_sha for the freshness
    gate. Exactly one subject is named — ``item_id`` (the numeric id or a
    public ref ``PREFIX-N`` / bare project-local number, resolved
    server-side via ``target.public_ref``) or ``deployment_run_id``. The
    result payload echoes the resolved subject. Raises ``RuntimeError``
    with the transport/handler error message on failure.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.domain.qa_composed_dispatch import (
        call_qa_function,
    )

    if deployment_run_id is not None:
        target = TargetRef(
            kind="deployment_run",
            deployment_run_id=str(deployment_run_id),
            project_id=project,
        )
    else:
        try:
            target = TargetRef(kind="item", item_id=int(item_id))
        except (TypeError, ValueError):
            target = TargetRef(
                kind="item",
                public_ref=str(item_id).strip(),
                project_id=project,
            )

    payload: Dict[str, Any] = {
        "project": project,
        "requirement_id": int(requirement_id),
    }
    if expected_branch:
        payload["expected_branch"] = expected_branch
    response = call_qa_function(
        function_id="qa.browser_context.get",
        target=target,
        payload=payload,
        actor=actor,
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        raise RuntimeError(f"qa.browser_context.get failed ({code}): {message}")
    return response.result or {}


__all__ = ["_fetch_browser_context"]

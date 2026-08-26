"""Record the hosting decision on the project during ``yoke onboard`` apply.

The wizard collects the answer before Review, but until it is written down it
lives only in the process that asked. That was the whole shape of the gap this
module closes: an operator who hosts elsewhere could say so, the wizard would
believe them, and then ``/yoke onboard`` would propose AWS Packs anyway because
nothing survived. Apply is the first moment both facts exist at once — the
answer, and a project id to attach it to — so this is where the row lands.

Only a declared posture is written. "Decide later" is expressed by having no
row, so an undecided answer writes nothing and ``/yoke onboard`` asks once.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_contracts import hosting_posture
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.config.project_onboard_support import (
    ProjectDispatchError,
    machine_config_path,
)
from yoke_cli.transport.dispatcher import call_dispatcher


def record(
    *,
    project: str,
    posture: str,
    provider_note: str | None = None,
    config_path: str | Path | None = None,
) -> Mapping[str, Any] | None:
    """Put the declared posture on ``project``; return ``None`` if undeclared.

    A ``put`` on a singleton family replaces whatever is there, so re-running
    the wizard with the same answer converges rather than conflicting.
    """
    if not hosting_posture.is_declared(posture):
        return None
    payload: dict[str, Any] = {"posture": posture}
    note = (provider_note or "").strip()
    if note:
        payload["provider"] = note
    ops = [{
        "op": "put",
        "family": hosting_posture.HOSTING_POSTURE_FAMILY,
        "attachment": "project",
        "payload": payload,
    }]
    with machine_config_path(config_path):
        response = call_dispatcher(
            function_id="project_structure.patch.apply",
            target=TargetRef(kind="project_structure", project_id=project),
            payload={"project_id": project, "ops": ops},
        )
    if not response.success:
        message = response.error.message if response.error else "unknown error"
        code = response.error.code if response.error else "unknown_error"
        raise ProjectDispatchError(
            "project_structure.patch.apply", code, message,
        )
    return response.result or {}


__all__ = ["record"]

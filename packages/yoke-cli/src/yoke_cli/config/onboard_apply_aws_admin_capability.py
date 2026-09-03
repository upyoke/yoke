"""Register the project's ``aws-admin`` capability row during Apply.

The wizard's AWS step writes the access-key pair to this machine and proves it
with a caller-identity probe, then reports the credential saved. Both halves of
"connected" have to exist for that to be true, and only one of them did: the
secret files landed under the machine secrets root, while the connected
universe gained no ``aws-admin`` row at all. ``/yoke onboard`` later asks
``projects.capability.has``, reads ``false``, and tells the operator to enter
two secrets that are already on disk.

The row cannot be written by the step that collects the credential, because at
that point the project it belongs to does not exist yet. Apply is the first
moment both facts are available — the answer, and a project to attach it to —
so the row lands here, beside the hosting posture, from the same inputs the
verified screen showed.

Merge rather than create: the settings merge starts an absent capability from
the empty object and CAS-updates an existing one, so a second wizard run over a
project that already has the row converges on the same document instead of
refusing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_contracts import hosting_posture
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.config import aws_admin_capability
from yoke_cli.config.project_onboard_support import (
    ProjectDispatchError,
    machine_config_path,
)
from yoke_cli.transport.dispatcher import call_dispatcher

#: Region key the credential resolver reads for project-scoped AWS clients.
REGION_KEY = "region"
#: Account the verified identity belongs to. Recorded when the probe named it;
#: an unverified pair leaves it out rather than guessing.
ACCOUNT_ID_KEY = "account_id"


def record(
    *,
    project: str,
    posture: str,
    verification: Mapping[str, Any] | None = None,
    config_path: str | Path | None = None,
) -> Mapping[str, Any] | None:
    """Register ``aws-admin`` for ``project``; ``None`` when it does not apply.

    Returns ``None`` for any posture other than Yoke-managed AWS, and for a
    managed-AWS answer whose credential pair is not on this machine — there is
    nothing to declare when the deploy could not read a credential anyway.
    """
    slug = str(project or "").strip()
    if not slug or posture != hosting_posture.POSTURE_YOKE_MANAGED_AWS:
        return None
    if not aws_admin_capability.credential_saved(slug):
        return None
    facts = dict(verification or {})
    assignments: dict[str, Any] = {
        REGION_KEY: (
            str(facts.get(REGION_KEY) or "").strip()
            or aws_admin_capability.default_region()
        ),
    }
    account = str(facts.get("account") or "").strip()
    if account:
        assignments[ACCOUNT_ID_KEY] = account
    with machine_config_path(config_path):
        response = call_dispatcher(
            function_id="projects.capability_settings.merge",
            target=TargetRef(kind="global"),
            payload={
                "project": slug,
                "cap_type": aws_admin_capability.CAPABILITY_TYPE,
                "assignments": assignments,
            },
        )
    if not response.success:
        message = response.error.message if response.error else "unknown error"
        code = response.error.code if response.error else "unknown_error"
        raise ProjectDispatchError(
            "projects.capability_settings.merge",
            code,
            message,
        )
    result = dict(response.result or {})
    result["settings"] = assignments
    return result


__all__ = ["ACCOUNT_ID_KEY", "REGION_KEY", "record"]

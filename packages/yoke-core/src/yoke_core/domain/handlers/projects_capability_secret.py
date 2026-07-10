"""``projects.capability.secret.set`` handler."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.machine_config.capability_secrets import (
    is_machine_local_capability_secret,
)
from yoke_core.domain.project_github_capability_settings import (
    reject_github_capability_secret_write,
)


class ProjectsCapabilitySecretSetRequest(BaseModel):
    project: str
    cap_type: str
    key: str
    value: str | None = None
    source: Literal["literal", "machine_file"] = "literal"
    path: str | None = None


class ProjectsCapabilitySecretSetResponse(BaseModel):
    project: str
    cap_type: str
    key: str
    source: str
    stored: bool


def handle_projects_capability_secret_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = ProjectsCapabilitySecretSetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )

    try:
        reject_github_capability_secret_write(parsed.cap_type)
    except ValueError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="github_binding_owned",
                message=str(exc),
                jsonpath="$.payload.cap_type",
            ),
        )

    if parsed.source == "machine_file":
        if not is_machine_local_capability_secret(parsed.cap_type, parsed.key):
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message=(
                        f"{parsed.cap_type}.{parsed.key} is not a "
                        "machine-local capability secret"
                    ),
                    jsonpath="$.payload",
                ),
            )
        if not parsed.path:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message="machine_file source requires path",
                    jsonpath="$.payload.path",
                ),
            )
        from yoke_core.domain.projects_capabilities import (
            cmd_capability_mark_machine_secret_file,
        )

        try:
            cmd_capability_mark_machine_secret_file(
                parsed.project,
                parsed.cap_type,
                parsed.key,
                parsed.path,
            )
        except (LookupError, ValueError) as exc:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message=str(exc),
                    jsonpath="$.payload",
                ),
            )
        return HandlerOutcome(
            result_payload={
                "project": parsed.project,
                "cap_type": parsed.cap_type,
                "key": parsed.key,
                "source": parsed.source,
                "stored": True,
                "path": parsed.path,
            },
            primary_success=True,
        )

    if parsed.value is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="literal source requires value",
                jsonpath="$.payload.value",
            ),
        )

    if is_machine_local_capability_secret(parsed.cap_type, parsed.key):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="machine_local_secret",
                message=(
                    f"{parsed.cap_type}.{parsed.key} is stored on the local "
                    "machine under ~/.yoke/secrets/capability-secrets; "
                    "use the local `yoke projects capability secret set` "
                    "CLI so the secret value is not relayed to Yoke API"
                ),
                jsonpath="$.payload",
            ),
        )

    from yoke_core.domain.projects_capabilities import cmd_capability_set_secret

    try:
        cmd_capability_set_secret(
            parsed.project,
            parsed.cap_type,
            parsed.key,
            value=parsed.value,
            source=parsed.source,
        )
    except (LookupError, ValueError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    return HandlerOutcome(
        result_payload={
            "project": parsed.project,
            "cap_type": parsed.cap_type,
            "key": parsed.key,
            "source": parsed.source,
            "stored": True,
        },
        primary_success=True,
    )


__all__ = [
    "ProjectsCapabilitySecretSetRequest",
    "ProjectsCapabilitySecretSetResponse",
    "handle_projects_capability_secret_set",
]

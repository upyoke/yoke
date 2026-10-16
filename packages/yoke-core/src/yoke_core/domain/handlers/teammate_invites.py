"""Org-admin teammate invitations and one-time code results."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, FunctionError, HandlerOutcome
from yoke_core.domain import db_backend, db_helpers, teammate_invite_codes as invites
from yoke_core.domain.actor_permissions import ROLE_OPERATOR
from yoke_core.domain.actor_role import ActorRoleRefused, require_human_org_role
from yoke_core.domain.handlers.identity_common import caller_actor_id


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InviteCreateRequest(_Model):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    role: str | None = None


class InviteListRequest(_Model):
    include_used: bool = False


class InviteIdRequest(_Model):
    invite_id: int = Field(gt=0, strict=True)


class InviteResponse(_Model):
    invite: dict[str, Any]


class InviteCreatedResponse(InviteResponse):
    code: str = Field(repr=False)
    expires_at: str
    guidance: dict[str, str]


class InviteListResponse(_Model):
    invite_form: Literal["email", "name", "local"]
    sign_in_method: Literal["yoke_account", "company_sign_in", "invite_code", "local"]
    invites: list[dict[str, Any]]


def _require_code_form() -> None:
    fact = invites.invite_form_fact()
    if fact["invite_form"] == "email":
        method = "a Yoke account" if fact["sign_in_method"] == "yoke_account" else "company sign-in"
        raise invites.TeammateInviteError(
            "invite_email_required", f"this server uses {method}; enter their email instead",
        )
    if fact["invite_form"] == "local":
        raise invites.TeammateInviteError(
            "invite_local_universe",
            "this universe is reachable here only; run `yoke self-host init` to invite teammates",
        )


def _created_result(created: invites.CreatedInvite) -> dict:
    return {
        "invite": created.invite, "code": created.code,
        "expires_at": created.invite["expires_at"],
        "guidance": {
            "send_to": f"send it to {created.invite['name']} only, through a private channel",
            "redeem_command": "yoke connect <origin>",
            "redeem_instruction": "Then choose Enter invite code.",
            "recovery": "If the code is lost, reissue the invite to receive a new code.",
        },
    }


def _create(conn, payload, request, actor_id):
    _require_code_form()
    role = payload.role if payload.role is not None else ROLE_OPERATOR
    require_human_org_role(role)
    return _created_result(invites.create_invite(
        conn, name=payload.name, role=role, inviter_actor_id=actor_id,
        request_id=request.request_id,
    ))


def _list(conn, payload, request, actor_id):
    fact = invites.invite_form_fact()
    return {**fact, "invites": invites.list_invites(conn, include_used=payload.include_used)}


def _revoke(conn, payload, request, actor_id):
    return {"invite": invites.revoke_invite(
        conn, invite_id=payload.invite_id, actor_id=actor_id,
    )}


def _reissue(conn, payload, request, actor_id):
    _require_code_form()
    return _created_result(invites.reissue_invite(
        conn, invite_id=payload.invite_id, actor_id=actor_id, request_id=request.request_id,
    ))


def _handle(request, model, operation) -> HandlerOutcome:
    try:
        payload = model.model_validate(request.payload or {})
        actor_id, error = caller_actor_id(request)
        if error is not None:
            return HandlerOutcome(primary_success=False, error=error)
        with db_helpers.connect() as conn:
            result = operation(conn, payload, request, actor_id)
        return HandlerOutcome(primary_success=True, result_payload=result)
    except invites.TeammateInviteError as exc:
        error = FunctionError(code=exc.code, message=exc.detail)
    except (ValidationError, ActorRoleRefused):
        error = FunctionError(
            code="payload_invalid",
            message="send a name of 1-80 characters, a person's org role, or a positive invite id as documented",
        )
    except db_backend.database_error_types():
        error = FunctionError(
            code="invite_store_unavailable",
            message="ask the server operator to check database health, then retry",
        )
    return HandlerOutcome(primary_success=False, error=error)


def handle_create(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle(request, InviteCreateRequest, _create)


def handle_list(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle(request, InviteListRequest, _list)


def handle_revoke(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle(request, InviteIdRequest, _revoke)


def handle_reissue(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle(request, InviteIdRequest, _reissue)

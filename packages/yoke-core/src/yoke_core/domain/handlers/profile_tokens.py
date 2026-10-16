"""Create and revoke the signed-in person's own API tokens."""

from __future__ import annotations

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.profile import _bound_actor, _error


MAX_TOKEN_NAME_LENGTH = 80


class ProfileTokenCreateRequest(BaseModel):
    name: str


class ProfileTokenCreateResponse(BaseModel):
    token_id: int
    name: str
    raw_token: str


class ProfileTokenRevokeRequest(BaseModel):
    token_id: int


class ProfileTokenRevokeResponse(BaseModel):
    token_id: int
    status: str


def handle_profile_token_create(request: FunctionCallRequest) -> HandlerOutcome:
    actor_id, invalid = _bound_actor(request, "profile.token.create")
    if invalid is not None:
        return invalid
    name = str((request.payload or {}).get("name") or "").strip()
    if not name or len(name) > MAX_TOKEN_NAME_LENGTH:
        return _error(
            "payload_invalid",
            f"name must be 1-{MAX_TOKEN_NAME_LENGTH} characters",
            jsonpath="$.payload.name",
        )
    from yoke_core.domain import db_helpers
    from yoke_core.domain.api_tokens import TokenCreationReplayed, mint_token

    conn = db_helpers.connect()
    try:
        created = mint_token(
            conn,
            actor_id=actor_id,
            name=name,
            creation_request_id=request.request_id,
        )
    except TokenCreationReplayed:
        return _error(
            "result_unavailable",
            "This request already created a token whose value cannot be shown again; "
            "revoke it (`yoke tokens list`, `yoke tokens revoke TOKEN-ID`) "
            "and create a new one",
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "token_id": created.token_id,
            "name": name,
            "raw_token": created.raw_token,
        },
        primary_success=True,
    )


def handle_profile_token_revoke(request: FunctionCallRequest) -> HandlerOutcome:
    actor_id, invalid = _bound_actor(request, "profile.token.revoke")
    if invalid is not None:
        return invalid
    raw_id = (request.payload or {}).get("token_id")
    if not isinstance(raw_id, int) or isinstance(raw_id, bool):
        return _error(
            "payload_invalid",
            "token_id must be an integer",
            jsonpath="$.payload.token_id",
        )
    from yoke_core.domain import db_helpers
    from yoke_core.domain.api_tokens import revoke_token

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT actor_id, machine_id, status FROM api_tokens WHERE id = %s",
            (raw_id,),
        ).fetchone()
        if row is None or int(row[0]) != actor_id:
            return _error(
                "token_not_found",
                f"token {raw_id} is not one of yours",
                jsonpath="$.payload.token_id",
            )
        if row[1]:
            return _error(
                "token_machine_bound",
                "this token belongs to a machine; retire the machine "
                "on the Machines page to end it",
                jsonpath="$.payload.token_id",
            )
        if row[2] != "active":
            return _error(
                "token_not_active",
                f"token {raw_id} is already {row[2]}",
            )
        revoke_token(conn, token_id=raw_id, actor_id=actor_id)
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"token_id": raw_id, "status": "revoked"},
        primary_success=True,
    )

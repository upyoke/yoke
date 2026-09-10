"""Profile handlers: the signed-in person's own page.

``profile.get`` reads everything the Profile page shows for the calling
actor in one dispatch (:mod:`yoke_core.domain.profile_read`). The four
mutations act only on the caller's own rows: a token is minted or revoked
for the bound actor, a preference is written for the bound actor, and the
onboarding reset deletes the bound actor's dismissal preferences and
nothing else. Every handler refuses cleanly without a bound actor,
because there is no profile to show or change for nobody.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

from yoke_core.domain.overview_activation_read import DISMISS_PREF_PREFIX
from yoke_core.domain.profile_read import (
    TIME_ZONE_PREF_KEY,
    hidden_module_count,
    read_actor,
    read_identity,
    read_preferences,
    read_roles,
    read_tokens,
)


PREFERENCE_KEYS = (TIME_ZONE_PREF_KEY,)

MAX_TOKEN_NAME_LENGTH = 80


class ProfileGetRequest(BaseModel):
    pass


class ProfileGetResponse(BaseModel):
    actor: Dict[str, Any]
    identity: Optional[Dict[str, Any]]
    roles: Dict[str, List[Dict[str, Any]]]
    tokens: List[Dict[str, Any]]
    preferences: Dict[str, Any]
    onboarding: Dict[str, Any]


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


class ProfilePreferenceSetRequest(BaseModel):
    key: str
    value: str


class ProfilePreferenceSetResponse(BaseModel):
    key: str
    value: str


class ProfileOnboardingResetRequest(BaseModel):
    pass


class ProfileOnboardingResetResponse(BaseModel):
    cleared: int


def _error(
    code: str, message: str, *, jsonpath: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _bound_actor(
    request: FunctionCallRequest, function_id: str,
) -> tuple[Optional[int], Optional[HandlerOutcome]]:
    if request.target.kind != "global":
        return None, _error(
            "target_invalid",
            f"{function_id} requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    raw = (request.actor.actor_id or "").strip()
    if not raw.isdigit():
        return None, _error(
            "actor_required",
            f"{function_id} reads and writes the calling person's own "
            "profile and needs a bound actor; this caller has none",
        )
    return int(raw), None


def handle_profile_get(request: FunctionCallRequest) -> HandlerOutcome:
    actor_id, invalid = _bound_actor(request, "profile.get")
    if invalid is not None:
        return invalid
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        actor = read_actor(conn, actor_id)
        if actor is None:
            return _error(
                "actor_unavailable",
                f"actor {actor_id} is not registered in this universe",
            )
        payload = {
            "actor": actor,
            "identity": read_identity(conn, actor_id),
            "roles": read_roles(conn, actor_id),
            "tokens": read_tokens(conn, actor_id),
            "preferences": read_preferences(conn, actor_id),
            "onboarding": {"hidden_count": hidden_module_count(conn, actor_id)},
        }
    finally:
        conn.close()
    return HandlerOutcome(result_payload=payload, primary_success=True)


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
    from yoke_core.domain.api_tokens import mint_token

    conn = db_helpers.connect()
    try:
        created = mint_token(conn, actor_id=actor_id, name=name)
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
            "payload_invalid", "token_id must be an integer",
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
                "token_not_active", f"token {raw_id} is already {row[2]}",
            )
        revoke_token(conn, token_id=raw_id, actor_id=actor_id)
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"token_id": raw_id, "status": "revoked"},
        primary_success=True,
    )


def handle_profile_preference_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    actor_id, invalid = _bound_actor(request, "profile.preference.set")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    key = payload.get("key")
    raw_value = payload.get("value")
    value = "" if raw_value is None else str(raw_value).strip()
    if key not in PREFERENCE_KEYS:
        return _error(
            "payload_invalid",
            f"key must be one of {', '.join(PREFERENCE_KEYS)}",
            jsonpath="$.payload.key",
        )
    if key == TIME_ZONE_PREF_KEY and value:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            return _error(
                "payload_invalid",
                f"{value!r} is not a known time zone; use an IANA name such "
                "as America/New_York, or an empty value for Automatic",
                jsonpath="$.payload.value",
            )
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        if value:
            conn.execute(
                "INSERT INTO actor_ui_preferences "
                "(actor_id, pref_key, value, updated_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (actor_id, pref_key) DO UPDATE SET "
                "value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
                (actor_id, key, value, db_helpers.iso8601_now()),
            )
        else:
            conn.execute(
                "DELETE FROM actor_ui_preferences "
                "WHERE actor_id = %s AND pref_key = %s",
                (actor_id, key),
            )
        conn.commit()
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"key": key, "value": value}, primary_success=True,
    )


def handle_profile_onboarding_reset(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    actor_id, invalid = _bound_actor(request, "profile.onboarding.reset")
    if invalid is not None:
        return invalid
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        cleared = hidden_module_count(conn, actor_id)
        conn.execute(
            "DELETE FROM actor_ui_preferences "
            "WHERE actor_id = %s AND pref_key LIKE %s",
            (actor_id, DISMISS_PREF_PREFIX + "%"),
        )
        conn.commit()
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"cleared": cleared}, primary_success=True,
    )


__all__ = [
    "PREFERENCE_KEYS",
    "TIME_ZONE_PREF_KEY",
    "handle_profile_get",
    "handle_profile_onboarding_reset",
    "handle_profile_preference_set",
    "handle_profile_token_create",
    "handle_profile_token_revoke",
]

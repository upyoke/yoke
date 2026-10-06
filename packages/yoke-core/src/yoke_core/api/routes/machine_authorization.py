"""Public start/poll door, using the same device-code wire as Cloud."""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from pydantic import ValidationError

from yoke_contracts.machine_authorization import (
    MachineAuthorizationPoll,
    MachineAuthorizationStart,
    START_PATH,
    POLL_PATH,
)
from yoke_core.domain import (
    db_backend,
    db_helpers,
    machine_authorization_codes as codes,
)
from yoke_core.domain.machine_registry import MachineRegistryError
from yoke_core.domain.actor_state import ActorDisabledError
from yoke_core.api.oidc_config import OidcConfigError, resolve_oidc_config

router = APIRouter()
_log = logging.getLogger("yoke.api.machine_authorization")


def _error(code: str, detail: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"error": code, "message": detail},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


@router.get(START_PATH)
def methods() -> JSONResponse:
    try:
        enabled = resolve_oidc_config() is not None
    except OidcConfigError as exc:
        return _error(
            "oidc_misconfigured",
            f"{exc}; ask the server operator to correct company sign-in settings",
            503,
        )
    return JSONResponse({"device_code": enabled}, headers={"Cache-Control": "no-store"})


@router.post(START_PATH)
async def start(request: Request) -> JSONResponse:
    try:
        model = MachineAuthorizationStart.model_validate(await request.json())
    except (ValidationError, ValueError):
        return _error(
            "machine_identity_required",
            "send this machine's configured id and name to start connection",
            400,
        )
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(_start, model)


def _start(model: MachineAuthorizationStart) -> JSONResponse:
    try:
        config = resolve_oidc_config()
    except OidcConfigError as exc:
        return _error(
            "oidc_misconfigured",
            f"{exc}; ask the server operator to correct company sign-in settings",
            503,
        )
    if config is None:
        return _error(
            "oidc_not_configured",
            "use yoke connect URL --token-stdin with an API token",
            409,
        )
    try:
        with db_helpers.connect() as conn:
            payload = codes.start(
                conn, origin=config.redirect_base_url, **model.model_dump()
            )
    except codes.MachineAuthorizationError as exc:
        return _error(exc.code, str(exc), exc.status)
    except db_backend.database_error_types() as exc:
        _log.error("authorization_store_unavailable: %s", type(exc).__name__)
        return _error(
            "authorization_store_unavailable",
            "ask the server operator to check database health, then retry",
            503,
        )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@router.post(POLL_PATH)
async def token(request: Request) -> JSONResponse:
    try:
        model = MachineAuthorizationPoll.model_validate(await request.json())
    except (ValidationError, ValueError):
        return _error(
            "machine_identity_required",
            "send a device code and this machine's configured id and name",
            400,
        )
    # Database work belongs to the worker pool, as on every authenticated door.
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(_poll, model)


def _poll(model: MachineAuthorizationPoll) -> JSONResponse:
    try:
        config = resolve_oidc_config()
        if config is None:
            return _error(
                "oidc_not_configured",
                "company sign-in was disabled; ask the server operator or connect using --token-stdin",
                409,
            )
        with db_helpers.connect() as conn:
            payload = codes.poll(
                conn, **model.model_dump(), origin=config.redirect_base_url
            )
    except codes.MachineAuthorizationError as exc:
        return _error(exc.code, str(exc), exc.status)
    except OidcConfigError as exc:
        return _error(
            "oidc_misconfigured",
            f"{exc}; ask the server operator to correct company sign-in settings",
            503,
        )
    except MachineRegistryError as exc:
        return _error(
            exc.code,
            f"{exc}; reconnect as this machine's owner, or ask an admin to inspect its registration",
            403,
        )
    except ActorDisabledError as exc:
        return _error("actor_disabled", str(exc), 403)
    except db_backend.database_error_types() as exc:
        _log.error("machine_credential_unavailable: %s", type(exc).__name__)
        return _error(
            "machine_credential_unavailable",
            "the credential could not be issued; retry this poll after checking server database health",
            503,
        )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})

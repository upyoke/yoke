"""Public start/poll door, using the same device-code wire as Cloud."""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from pydantic import ValidationError

from yoke_contracts.machine_authorization import (
    MachineAuthorizationPoll,
    MachineAuthorizationStart,
    HostedMachineAuthorizationError,
    parse_authorization_response,
    MachineAuthorizationRefused,
    POLL_OUTCOMES,
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
from yoke_core.domain.machine_authorization_limits import admit_client
from yoke_core.api.oidc_config import OidcConfigError, resolve_oidc_config

router = APIRouter()
_log = logging.getLogger("yoke.api.machine_authorization")


def _error(
    code: str, detail: str, status: int, *, retry_after: int = 0
) -> JSONResponse:
    expected_status, model = POLL_OUTCOMES.get(
        code, (status, MachineAuthorizationRefused)
    )
    if expected_status != status:
        raise ValueError(
            "authorization_response_status_invalid: correct the route outcome status"
        )
    return JSONResponse(
        model(error=code, message=detail).model_dump(exclude_none=True),
        status_code=status,
        headers={
            "Cache-Control": "no-store",
            **({"Retry-After": str(retry_after)} if retry_after else {}),
        },
    )


def _success(payload: dict, *, operation: str) -> JSONResponse:
    try:
        response = parse_authorization_response(payload, 200, operation=operation)
    except HostedMachineAuthorizationError:
        _log.error(
            "authorization_response_invalid: %s success body violated the shared contract",
            operation,
        )
        return _error(
            "authorization_response_invalid",
            "ask the server operator to correct its machine sign-in contract, then start a fresh connection",
            500,
        )
    return JSONResponse(response.model_dump(), headers={"Cache-Control": "no-store"})


def _admit(request: Request, operation: str) -> str | JSONResponse:
    try:
        with db_helpers.connect() as conn:
            key, delay = admit_client(
                conn,
                client=request.client.host if request.client else "unknown",
                operation=operation,
            )
    except db_backend.database_error_types() as exc:
        _log.error("authorization_store_unavailable: %s", type(exc).__name__)
        return _error(
            "authorization_store_unavailable",
            "restore the sign-in admission store, then retry",
            503,
        )
    if delay:
        return _error(
            f"authorization_{operation}_rate_limited",
            "too many requests from this client; retry after Retry-After",
            429,
            retry_after=delay,
        )
    return key


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
    from starlette.concurrency import run_in_threadpool

    client_key = await run_in_threadpool(_admit, request, "start")
    if isinstance(client_key, JSONResponse):
        return client_key
    try:
        model = MachineAuthorizationStart.model_validate(await request.json())
    except (ValidationError, ValueError):
        return _error(
            "machine_identity_required",
            "send this machine's configured id and name to start connection",
            400,
        )
    return await run_in_threadpool(_start, model, client_key)


def _start(model: MachineAuthorizationStart, client_key: str) -> JSONResponse:
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
                conn,
                origin=config.redirect_base_url,
                client_key=client_key,
                **model.model_dump(),
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
    return _success(payload, operation="start")


@router.post(POLL_PATH)
async def token(request: Request) -> JSONResponse:
    from starlette.concurrency import run_in_threadpool

    client_key = await run_in_threadpool(_admit, request, "poll")
    if isinstance(client_key, JSONResponse):
        return client_key
    try:
        model = MachineAuthorizationPoll.model_validate(await request.json())
    except (ValidationError, ValueError):
        return _error(
            "machine_identity_required",
            "send a device code and this machine's configured id and name",
            400,
        )
    # Database work belongs to the worker pool, as on every authenticated door.
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
    return _success(payload, operation="poll")

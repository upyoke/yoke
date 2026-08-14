"""HTTPS relay for Yoke function-call envelopes."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from yoke_cli.api_urls import FUNCTIONS_CALL_PATH, HEALTH_PATH, join_api_url
from yoke_cli.config.machine_config import active_connection
from yoke_cli.transport.bounded_http_open_policy import (
    HttpOpenPolicyError,
    open_bounded_request,
)
from yoke_cli.transport.https_engine_handshake import (
    ServerHandshake,
    observe_server_version,
)
from yoke_cli.transport.https_response_policy import (
    HttpsResponsePolicyError,
    adopt_boundary_error,
    collect_request_secrets,
    parse_typed_response,
    read_bounded_response,
    redact_text,
    safe_excerpt,
)
from yoke_cli.transport.https_urlopen import open_no_redirect
from yoke_cli.transport.response_deadline_open import (
    ResponseOpenDeadlineError,
)
from yoke_cli.transport.response_deadline_read import deadline_after
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_contracts.machine_config.schema import (
    CREDENTIAL_KIND_TOKEN_FILE,
    MachineConfigContractError,
    TRANSPORT_HTTPS,
)

_DEFAULT_TIMEOUT_S = 30.0
_TRANSPORT_ATTEMPTS = 2
_RETRYABLE_RESPONSE_ERROR = "HTTPS function relay response exceeded the time limit"
_NETWORK_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    OSError,
    http.client.HTTPException,
)
_DEFAULT_OPEN_NO_REDIRECT = open_no_redirect


class TransportError(RuntimeError):
    """The active connection cannot relay this request; message names the fix."""


@dataclass(frozen=True)
class HttpsConnection:
    """Resolved HTTPS relay target: endpoint + bearer token."""

    api_url: str
    token: str
    env: str = ""

    @property
    def functions_url(self) -> str:
        return join_api_url(self.api_url, FUNCTIONS_CALL_PATH)


def resolve_https_connection(
    path: str | Path | None = None,
    *,
    explicit_env: str | None = None,
) -> Optional[HttpsConnection]:
    """Return the HTTPS relay target, or ``None`` for local transport."""

    try:
        connection = active_connection(path, explicit_env=explicit_env)
    except MachineConfigContractError:
        return None
    if str(connection.get("transport") or "") != TRANSPORT_HTTPS:
        return None

    env_name = str(connection.get("env") or "<env>")
    api_url = str(connection.get("api_url") or "").strip()
    if not api_url:
        raise TransportError(
            f"env {env_name!r} declares https transport but no api_url; "
            f"repair it with `yoke connection set {env_name} --api-url ...`"
        )
    return HttpsConnection(
        api_url=api_url,
        token=_resolve_token(connection),
        env=env_name,
    )


def _resolve_token(connection) -> str:
    source = connection.get("credential_source")
    source = source if isinstance(source, dict) else {}
    kind = str(source.get("kind") or "")
    if kind == CREDENTIAL_KIND_TOKEN_FILE:
        token_path = Path(str(source.get("path") or "")).expanduser()
        try:
            token = token_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise TransportError(
                f"https credential token_file is unreadable: {exc}; "
                "repair it with `yoke auth set <env> TOKEN` "
                "(yoke status diagnoses the active config)"
            ) from exc
        if not token:
            raise TransportError(f"https credential token_file {token_path} is empty")
        return token
    raise TransportError(
        "https transport requires credential_source.kind 'token_file' "
        f"(got {kind or 'nothing'}); store the actor token with "
        "`yoke auth set <env> TOKEN`"
    )


def relay_https(
    request: FunctionCallRequest,
    connection: HttpsConnection,
    *,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    handshake: Optional[ServerHandshake] = None,
) -> FunctionCallResponse:
    """POST the envelope to the active env; parse the typed response."""

    payload = request.model_dump(mode="json")
    sensitive_values = collect_request_secrets(
        request, transport_token=connection.token
    )
    try:
        deadline = deadline_after(timeout_s)
    except ValueError:
        return _transport_error_response(
            request,
            connection,
            "HTTPS function relay timeout must be positive and finite",
            sensitive_values=sensitive_values,
        )
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(_TRANSPORT_ATTEMPTS):
        if attempt:
            deadline = deadline_after(timeout_s)
        http_request = urllib.request.Request(
            connection.functions_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {connection.token}",
            },
        )
        try:
            opened = _open_function_relay(
                http_request,
                deadline=deadline,
                timeout_s=timeout_s,
            )
            with opened as resp:
                observe_server_version(
                    getattr(resp, "headers", None), sensitive_values, handshake
                )
                raw = read_bounded_response(resp, deadline=deadline)
        except urllib.error.HTTPError as exc:
            return _http_error_response(
                request, connection, exc, deadline=deadline,
                sensitive_values=sensitive_values, handshake=handshake,
            )
        except HttpsResponsePolicyError as exc:
            if (
                str(exc) == _RETRYABLE_RESPONSE_ERROR
                and attempt + 1 < _TRANSPORT_ATTEMPTS
            ):
                continue
            return _transport_error_response(
                request, connection, str(exc), sensitive_values=sensitive_values,
            )
        except ResponseOpenDeadlineError:
            if attempt + 1 < _TRANSPORT_ATTEMPTS:
                continue
            return _transport_error_response(
                request, connection, _RETRYABLE_RESPONSE_ERROR,
                sensitive_values=sensitive_values,
            )
        except _NETWORK_ERRORS:
            if attempt + 1 < _TRANSPORT_ATTEMPTS:
                continue
            return _network_error_response(
                request, connection, sensitive_values=sensitive_values
            )
        break
    try:
        return parse_typed_response(raw, sensitive_values=sensitive_values)
    except HttpsResponsePolicyError as exc:
        return _transport_error_response(
            request,
            connection,
            str(exc),
            sensitive_values=sensitive_values,
        )


def _open_function_relay(
    request: urllib.request.Request,
    *,
    deadline: float,
    timeout_s: float,
):
    if open_no_redirect is not _DEFAULT_OPEN_NO_REDIRECT:
        return open_no_redirect(request, timeout=timeout_s)
    try:
        return open_bounded_request(
            request,
            deadline=deadline,
            replay_safe=False,
            allow_loopback_http=True,
            opener=None,
        )
    except HttpOpenPolicyError as exc:
        raise HttpsResponsePolicyError(str(exc)) from exc


def _http_error_response(
    request: FunctionCallRequest,
    connection: HttpsConnection,
    exc: urllib.error.HTTPError,
    *,
    deadline: float,
    sensitive_values: tuple[str, ...],
    handshake: Optional[ServerHandshake] = None,
) -> FunctionCallResponse:
    observe_server_version(getattr(exc, "headers", None), sensitive_values, handshake)
    try:
        raw = read_bounded_response(exc, deadline=deadline)
    except HttpsResponsePolicyError as read_error:
        return _transport_error_response(
            request,
            connection,
            str(read_error),
            sensitive_values=sensitive_values,
        )
    except _NETWORK_ERRORS:
        return _network_error_response(
            request, connection, sensitive_values=sensitive_values
        )
    try:
        return parse_typed_response(raw, sensitive_values=sensitive_values)
    except HttpsResponsePolicyError:
        adopted = adopt_boundary_error(request, raw, sensitive_values=sensitive_values)
        if adopted is not None:
            return adopted
        excerpt = safe_excerpt(raw, sensitive_values=sensitive_values)
        detail = f": {excerpt}" if excerpt else ""
        return _transport_error_response(
            request,
            connection,
            f"{connection.functions_url} returned HTTP {exc.code} "
            f"with a non-envelope body{detail}",
            sensitive_values=sensitive_values,
        )


def _network_error_response(
    request: FunctionCallRequest,
    connection: HttpsConnection,
    *,
    sensitive_values: tuple[str, ...],
) -> FunctionCallResponse:
    return _transport_error_response(
        request,
        connection,
        "could not reach the HTTPS function relay endpoint",
        sensitive_values=sensitive_values,
    )


def _transport_error_response(
    request: FunctionCallRequest,
    connection: HttpsConnection,
    detail: str,
    *,
    sensitive_values: tuple[str, ...] = (),
) -> FunctionCallResponse:
    health_url = join_api_url(connection.api_url, HEALTH_PATH)
    safe_detail = redact_text(detail, sensitive_values)
    recovery_hint = redact_text(
        "Verify the active env and credential with `yoke status`; "
        "repair ~/.yoke/config.json per `yoke config example`. "
        f"The env's public health endpoint is {health_url}.",
        sensitive_values,
    )
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(
            code="https_transport_failed",
            message=safe_detail,
            recovery_hint=recovery_hint,
        ),
    )


__all__ = [
    "HttpsConnection",
    "ServerHandshake",
    "TransportError",
    "relay_https",
    "resolve_https_connection",
]

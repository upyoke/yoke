"""HTTPS relay for Yoke function-call envelopes."""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from yoke_cli.api_urls import FUNCTIONS_CALL_PATH, join_api_url
from yoke_cli.config.machine_config import active_connection
from yoke_cli.transport.bounded_http_open_policy import (
    HttpOpenPolicyError,
    open_bounded_request,
)
from yoke_cli.transport.https_relay_outcome import (
    record_outcome,
    transport_error_response,
)
from yoke_cli.transport.https_retry_policy import (
    CONNECTION_ATTEMPTS,
    RESPONSE_DEADLINE_ATTEMPTS,
    connection_backoff_seconds,
    http_status_is_transient,
    should_retry_connection,
    write_retry_notice,
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
)
from yoke_contracts.machine_config.schema import (
    CREDENTIAL_KIND_TOKEN_FILE,
    MachineConfigContractError,
    TRANSPORT_HTTPS,
)

_DEFAULT_TIMEOUT_S = 30.0
_RETRYABLE_RESPONSE_ERROR = "HTTPS function relay response exceeded the time limit"
_UNREACHABLE = "could not reach the HTTPS function relay endpoint"
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
    max_attempts: Optional[int] = None,
    sleep=time.sleep,
) -> FunctionCallResponse:
    """POST the envelope to the active env; parse the typed response.

    Counts what it took, so a relay that only answered on the third try is
    visible later instead of being inferred from operator reports.
    """
    response, attempts = _relay_attempts(
        request, connection, timeout_s=timeout_s,
        handshake=handshake, max_attempts=max_attempts, sleep=sleep,
    )
    record_outcome(request, response, env=connection.env, attempts=attempts)
    return response


def _relay_attempts(
    request: FunctionCallRequest,
    connection: HttpsConnection,
    *,
    timeout_s: float,
    handshake: Optional[ServerHandshake],
    sleep,
    max_attempts: Optional[int] = None,
) -> tuple[FunctionCallResponse, int]:
    payload = request.model_dump(mode="json")
    sensitive_values = collect_request_secrets(
        request, transport_token=connection.token
    )
    try:
        deadline = deadline_after(timeout_s)
    except ValueError:
        return _refuse(
            request, connection,
            "HTTPS function relay timeout must be positive and finite",
            sensitive_values=sensitive_values,
        ), 1
    # Serialized once: every attempt carries the same request_id, which is
    # what makes a repeat safe against a call that already landed.
    body = json.dumps(payload).encode("utf-8")
    budget = min(max(max_attempts or CONNECTION_ATTEMPTS, 1), CONNECTION_ATTEMPTS)
    attempt = 0
    for attempt in range(budget):
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
            # Decided from the status alone, before the body is touched: a
            # 5xx is the box rather than an answer about this request, and
            # reading it only to discard it would spend the response's one
            # bounded read on a reply we are about to ask for again.
            if (
                http_status_is_transient(getattr(exc, "code", None))
                and should_retry_connection(attempt, budget=budget)
            ):
                backoff = connection_backoff_seconds(attempt)
                write_retry_notice(f"server returned {exc.code}", attempt, backoff)
                sleep(backoff)
                continue
            return _http_error_response(
                request, connection, exc, deadline=deadline,
                sensitive_values=sensitive_values, handshake=handshake,
            ), attempt + 1
        except HttpsResponsePolicyError as exc:
            if (
                str(exc) == _RETRYABLE_RESPONSE_ERROR
                and attempt + 1 < min(RESPONSE_DEADLINE_ATTEMPTS, budget)
            ):
                continue
            return _refuse(
                request, connection, str(exc),
                sensitive_values=sensitive_values,
            ), attempt + 1
        except ResponseOpenDeadlineError:
            if attempt + 1 < min(RESPONSE_DEADLINE_ATTEMPTS, budget):
                continue
            return _refuse(
                request, connection, _RETRYABLE_RESPONSE_ERROR,
                sensitive_values=sensitive_values,
            ), attempt + 1
        except _NETWORK_ERRORS as exc:
            if should_retry_connection(attempt, connection.api_url, exc, budget):
                backoff = connection_backoff_seconds(attempt)
                write_retry_notice("relay unreachable", attempt, backoff)
                sleep(backoff)
                continue
            return _refuse(
                request, connection, _UNREACHABLE, error=exc,
                attempts=attempt + 1, sensitive_values=sensitive_values,
            ), attempt + 1
        break
    try:
        return parse_typed_response(
            raw, sensitive_values=sensitive_values
        ), attempt + 1
    except HttpsResponsePolicyError as exc:
        return _refuse(
            request, connection, str(exc),
            sensitive_values=sensitive_values,
        ), attempt + 1


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
        return _refuse(
            request, connection, str(read_error),
            sensitive_values=sensitive_values,
        )
    except _NETWORK_ERRORS:
        return _refuse(
            request, connection, _UNREACHABLE,
            attempts=1, sensitive_values=sensitive_values,
        )
    try:
        return parse_typed_response(raw, sensitive_values=sensitive_values)
    except HttpsResponsePolicyError:
        adopted = adopt_boundary_error(request, raw, sensitive_values=sensitive_values)
        if adopted is not None:
            return adopted
        excerpt = safe_excerpt(raw, sensitive_values=sensitive_values)
        detail = f": {excerpt}" if excerpt else ""
        return _refuse(
            request, connection,
            f"{connection.functions_url} returned HTTP {exc.code} "
            f"with a non-envelope body{detail}",
            sensitive_values=sensitive_values,
        )


def _refuse(
    request: FunctionCallRequest,
    connection: HttpsConnection,
    detail: str,
    *,
    attempts: Optional[int] = None,
    error: BaseException | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> FunctionCallResponse:
    return transport_error_response(
        request,
        connection.api_url,
        detail,
        attempts=attempts,
        error=error,
        sensitive_values=sensitive_values,
    )


__all__ = [
    "HttpsConnection",
    "ServerHandshake",
    "TransportError",
    "relay_https",
    "resolve_https_connection",
]

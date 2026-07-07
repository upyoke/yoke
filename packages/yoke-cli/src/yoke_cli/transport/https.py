"""HTTPS relay for Yoke function-call envelopes."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from yoke_cli.api_urls import FUNCTIONS_CALL_PATH, HEALTH_PATH, join_api_url
from yoke_cli.config.machine_config import active_connection
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_contracts.engine_version import (
    ENGINE_VERSION_HEADER,
    local_handshake_version,
)
from yoke_contracts.machine_config.schema import (
    CREDENTIAL_KIND_TOKEN_FILE,
    MachineConfigContractError,
    TRANSPORT_HTTPS,
)

_DEFAULT_TIMEOUT_S = 30.0

# Process-wide latch: the engine-version skew warning prints at most once.
_skew_warned = False


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
            raise TransportError(
                f"https credential token_file {token_path} is empty"
            )
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
) -> FunctionCallResponse:
    """POST the envelope to the active env; parse the typed response."""

    body = json.dumps(request.model_dump(mode="json")).encode("utf-8")
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
        with urllib.request.urlopen(http_request, timeout=timeout_s) as resp:
            _warn_on_engine_version_skew(getattr(resp, "headers", None))
            return _parse_response(resp.read())
    except urllib.error.HTTPError as exc:
        _warn_on_engine_version_skew(getattr(exc, "headers", None))
        try:
            raw = exc.read()
        except OSError:
            raw = b""
        try:
            return _parse_response(raw)
        except TransportError:
            adopted = _adopt_boundary_error(request, raw)
            if adopted is not None:
                return adopted
            excerpt = raw.decode("utf-8", errors="replace").strip()[:200]
            detail = f": {excerpt}" if excerpt else ""
            return _transport_error_response(
                request,
                connection,
                f"{connection.functions_url} returned HTTP {exc.code} "
                f"with a non-envelope body{detail}",
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return _transport_error_response(
            request,
            connection,
            f"could not reach {connection.functions_url}: {exc}",
        )


def _warn_on_engine_version_skew(headers) -> None:
    """Print one stderr warning per process when server/client versions skew.

    Advisory only — never blocks the relay, never repeats, and stays
    silent when the header is absent (older server / source run), the
    local version is unresolvable, or the versions match.
    """
    global _skew_warned
    if _skew_warned or headers is None:
        return
    get = getattr(headers, "get", None)
    if not callable(get):
        return
    server_version = str(get(ENGINE_VERSION_HEADER) or "")
    if not server_version:
        return
    local_version = local_handshake_version()
    if not local_version or local_version == server_version:
        return
    _skew_warned = True
    print(
        f"yoke: server engine version {server_version} differs from the "
        f"local install {local_version}; commands still relay — update "
        "the older side if behavior looks off",
        file=sys.stderr,
    )


def _parse_response(raw: bytes) -> FunctionCallResponse:
    try:
        payload = json.loads(raw.decode("utf-8"))
        return FunctionCallResponse.model_validate(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise TransportError(f"response body is not a typed envelope: {exc}")


def _adopt_boundary_error(
    request: FunctionCallRequest, raw: bytes
) -> Optional[FunctionCallResponse]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("success") is not False:
        return None
    error = payload.get("error")
    if not isinstance(error, dict) or not error.get("code"):
        return None
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(
            code=str(error.get("code")),
            message=str(error.get("message") or ""),
            recovery_hint=error.get("recovery_hint"),
        ),
    )


def _transport_error_response(
    request: FunctionCallRequest,
    connection: HttpsConnection,
    detail: str,
) -> FunctionCallResponse:
    health_url = join_api_url(connection.api_url, HEALTH_PATH)
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(
            code="https_transport_failed",
            message=detail,
            recovery_hint=(
                "Verify the active env and credential with `yoke status`; "
                "repair ~/.yoke/config.json per `yoke config example`. "
                f"The env's public health endpoint is {health_url}."
            ),
        ),
    )


__all__ = [
    "HttpsConnection",
    "TransportError",
    "relay_https",
    "resolve_https_connection",
]

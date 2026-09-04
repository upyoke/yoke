"""Function-call dispatcher transport selection for the Yoke CLI."""

from __future__ import annotations

import importlib
import os
import uuid
from typing import Any, Callable, Dict, Optional

from yoke_cli.config import machine_config
from yoke_cli.transport import function_version_skew
from yoke_cli.transport import https as https_transport
from yoke_cli.transport import local_github_dispatch
from yoke_cli.transport.public_ref_display import emit_response
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.engine_version import local_handshake_version
from yoke_contracts.session_identity import (
    ANCHORS_DIR_NAME,
    CURSOR_SESSION_MAP_DIR_NAME,
    resolve_ambient_session_id,
)

LocalDispatch = Callable[[FunctionCallRequest], FunctionCallResponse]
HintResolver = Callable[[str], str]


def build_actor(
    *,
    actor_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> ActorContext:
    resolved_session = session_id or _resolve_session_id() or ""
    resolved_actor = actor_id or os.environ.get("YOKE_ACTOR_ID") or None
    return ActorContext(actor_id=resolved_actor, session_id=resolved_session)


_label_overrides_loaded = False
_label_overrides_value: Dict[str, str] = {}


def _client_label_overrides() -> Dict[str, str]:
    """The project's label-color override delta, resolved once per process.

    The client has the checkout, so it reads ``.yoke/labels`` and ships the
    delta in the request envelope; the server applies it without touching a
    file. Empty (the common case — a project that does not override) attaches
    nothing.
    """
    global _label_overrides_loaded, _label_overrides_value
    if not _label_overrides_loaded:
        try:
            from pathlib import Path

            from yoke_cli.config.checkout_context import resolve_repo_root_from_cwd
            from yoke_contracts.project_contract.label_policy import (
                overrides_delta,
                read_labels_file,
            )

            root = resolve_repo_root_from_cwd()
            labels = Path(root) / ".yoke" / "labels" if root else None
            _label_overrides_value = (
                dict(overrides_delta(read_labels_file(labels))) if labels else {}
            )
        except Exception:
            _label_overrides_value = {}
        _label_overrides_loaded = True
    return _label_overrides_value


def build_request(
    *,
    function_id: str,
    target: TargetRef,
    payload: Optional[Dict[str, Any]] = None,
    options: Optional[Dict[str, Any]] = None,
    preconditions: Optional[Dict[str, Any]] = None,
    actor: Optional[ActorContext] = None,
    request_id: Optional[str] = None,
    intent: Optional[str] = None,
    version: str = "v1",
) -> FunctionCallRequest:
    opts = dict(options or {})
    overrides = _client_label_overrides()
    if overrides and "label_color_overrides" not in opts:
        opts["label_color_overrides"] = dict(overrides)
    return FunctionCallRequest(
        function=function_id,
        version=version,
        actor=actor or build_actor(),
        target=target,
        request_id=request_id or str(uuid.uuid4()),
        intent=intent,
        payload=dict(payload or {}),
        preconditions=dict(preconditions or {}),
        options=opts,
    )


def call_dispatcher(
    *,
    function_id: str,
    target: TargetRef,
    payload: Optional[Dict[str, Any]] = None,
    options: Optional[Dict[str, Any]] = None,
    preconditions: Optional[Dict[str, Any]] = None,
    actor: Optional[ActorContext] = None,
    request_id: Optional[str] = None,
    intent: Optional[str] = None,
    timeout_s: Optional[float] = None,
    max_attempts: Optional[int] = None,
    local_only: bool = False,
    _local_dispatch: Optional[LocalDispatch] = None,
    _function_hint: Optional[HintResolver] = None,
    sensitive_values: tuple[str, ...] = (),
) -> FunctionCallResponse:
    """Build a request envelope and route it via the active transport.

    Routing is connection-keyed: an https active connection relays the
    envelope to the server; any other connection dispatches in-process
    through the engine. For a non-prod local-postgres universe that
    in-process dispatch IS the product path — the credentials in the
    active connection, not the transport mechanics, are the authority
    boundary. Prod-flagged postgres connections are operator-only by
    doctrine: the client-side handler pre-load declines them (see
    :func:`yoke_cli.commands._helpers.ensure_handlers_loaded`).
    """

    request = build_request(
        function_id=function_id,
        target=target,
        payload=payload,
        options=options,
        preconditions=preconditions,
        actor=actor,
        request_id=request_id,
        intent=intent,
    )
    if local_only:
        return _redact_response(
            _call_local(request, _local_dispatch, client_local=True), sensitive_values,
        )
    try:
        https = https_transport.resolve_https_connection()
    except https_transport.TransportError as exc:
        return _redact_response(_error_response(
            request, "https_transport_misconfigured", str(exc)
        ), sensitive_values)
    if https is not None:
        handshake = https_transport.ServerHandshake()
        relay_kwargs: Dict[str, Any] = {"handshake": handshake}
        if timeout_s is not None:
            relay_kwargs["timeout_s"] = timeout_s
        if max_attempts is not None:
            relay_kwargs["max_attempts"] = max_attempts
        response = https_transport.relay_https(request, https, **relay_kwargs)
        return _redact_response(
            _apply_version_skew_gate(
                response, request, https, handshake, _function_hint
            ),
            sensitive_values,
        )
    return _redact_response(
        _call_local(request, _local_dispatch), sensitive_values,
    )


def _redact_response(
    response: FunctionCallResponse,
    sensitive_values: tuple[str, ...],
) -> FunctionCallResponse:
    secrets = tuple(value for value in sensitive_values if value)
    if not secrets:
        return response

    def redact(value: Any) -> Any:
        if isinstance(value, str):
            for secret in secrets:
                value = value.replace(secret, "<redacted>")
            return value
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        return value

    return FunctionCallResponse.model_validate(
        redact(response.model_dump(mode="python"))
    )


def response_to_dict(response: FunctionCallResponse) -> Dict[str, Any]:
    return response.model_dump(mode="json")


def _resolve_session_id() -> Optional[str]:
    """Resolve the caller's harness session via the canonical ambient chain.

    Everything past the env chain is load-bearing on the https transport:
    the remote server cannot inspect the caller's process tree, so the
    client MUST stamp the session here. Delegating to the shared
    :func:`yoke_contracts.session_identity.resolve_ambient_session_id`
    keeps the client resolver in lockstep with the engine core — an
    env-only copy here silently dropped the ancestry fallback and denied
    every mutating CLI call from a harness with no session env var.
    """
    try:
        home = machine_config.yoke_home()
        return resolve_ambient_session_id(
            home / ANCHORS_DIR_NAME, os.environ,
            cursor_map_dir=home / CURSOR_SESSION_MAP_DIR_NAME,
        )
    except Exception:  # never break dispatch on identity resolution
        return None


def _call_local(
    request: FunctionCallRequest,
    local_dispatch: Optional[LocalDispatch],
    client_local: bool = False,
) -> FunctionCallResponse:
    dispatch_module = None
    if local_dispatch is None:
        try:
            dispatch_module = importlib.import_module(
                "yoke_core.domain.yoke_function_dispatch"
            )
        except ImportError as exc:
            return _error_response(
                request,
                "local_postgres_core_unavailable",
                "the active connection dispatches in-process through the "
                f"yoke-core engine, which is not importable here: {exc}",
                recovery_hint=(
                    "A local universe dispatches in-process by design. "
                    "Repair the install so the yoke-core engine imports, "
                    "or switch to an HTTPS connection with "
                    "`yoke env use <env>`."
                ),
            )
        local_dispatch = getattr(dispatch_module, "dispatch_local" if client_local else "dispatch")
    return local_github_dispatch.call_with_machine_github_authorization(
        request,
        local_dispatch,
        core_available=dispatch_module is not None,
    )


def _apply_version_skew_gate(
    response: FunctionCallResponse,
    request: FunctionCallRequest,
    connection: "https_transport.HttpsConnection",
    handshake: "https_transport.ServerHandshake",
    function_hint: Optional[HintResolver],
) -> FunctionCallResponse:
    """Retype a relayed unserved-function answer as client/server skew.

    The server says ``function_not_registered`` about its own registry;
    for a function this build can dispatch, that answer is a version-skew
    fact and is replaced with the typed error naming both engine versions
    and the direction-matched recovery. A function id this build does not
    know is a genuine unknown function, so the server's answer stands.
    """
    if response.success or response.error is None:
        return response
    if response.error.code != "function_not_registered":
        return response
    if request.function not in function_version_skew.local_function_ids():
        return response
    extra_hint = function_hint(request.function) if function_hint else ""
    return response.model_copy(
        update={
            "error": function_version_skew.skew_error(
                function_id=request.function,
                client_version=local_handshake_version(),
                server_version=handshake.engine_version,
                env_name=connection.env,
                extra_hint=extra_hint or "",
            )
        }
    )


def _error_response(
    request: FunctionCallRequest,
    code: str,
    message: str,
    *,
    recovery_hint: str | None = None,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(
            code=code,
            message=message,
            recovery_hint=recovery_hint,
        ),
    )


__all__ = [
    "build_actor",
    "build_request",
    "call_dispatcher",
    "emit_response",
    "response_to_dict",
]

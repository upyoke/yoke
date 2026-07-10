"""Function-call dispatcher transport selection for the Yoke CLI."""

from __future__ import annotations

import importlib
import json
import os
import sys
import uuid
from typing import Any, Callable, Dict, Optional

from yoke_cli.config import machine_config
from yoke_cli.transport import https as https_transport
from yoke_cli.transport import local_github_dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.session_identity import (
    ANCHORS_DIR_NAME,
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
    local_only: bool = False,
    _local_dispatch: Optional[LocalDispatch] = None,
    _function_hint: Optional[HintResolver] = None,
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
        return _call_local(request, _local_dispatch)
    try:
        https = https_transport.resolve_https_connection()
    except https_transport.TransportError as exc:
        return _error_response(
            request, "https_transport_misconfigured", str(exc)
        )
    if https is not None:
        response = (
            https_transport.relay_https(request, https, timeout_s=timeout_s)
            if timeout_s is not None
            else https_transport.relay_https(request, https)
        )
        return _enrich_https_function_drift(response, request, _function_hint)
    return _call_local(request, _local_dispatch)


def response_to_dict(response: FunctionCallResponse) -> Dict[str, Any]:
    return response.model_dump(mode="json")


def emit_response(
    response: FunctionCallResponse,
    *,
    json_mode: bool,
    human_writer=None,
) -> int:
    if json_mode:
        print(json.dumps(response_to_dict(response), sort_keys=True))
    else:
        if human_writer is not None and response.success:
            human_writer(response, sys.stdout, sys.stderr)
        else:
            _default_human_writer(response, sys.stdout, sys.stderr)
    return 0 if response.success else 1


def _resolve_session_id() -> Optional[str]:
    """Resolve the caller's harness session via the canonical ambient chain.

    Env chain first, then the hook-written process-anchor ancestry registry.
    The ancestry fallback is load-bearing on the https transport: the remote
    server cannot inspect the caller's process tree, so the client MUST stamp
    the session here. Delegating to the shared
    :func:`yoke_contracts.session_identity.resolve_ambient_session_id`
    keeps the client resolver in lockstep with the engine core — an
    env-only copy here silently dropped the ancestry fallback and denied
    every mutating CLI call from a harness that does not export a session
    env var (e.g. Claude Desktop) on https.
    """
    try:
        anchors_dir = machine_config.yoke_home() / ANCHORS_DIR_NAME
        return resolve_ambient_session_id(anchors_dir, os.environ)
    except Exception:  # never break dispatch on identity resolution
        return None


def _call_local(
    request: FunctionCallRequest,
    local_dispatch: Optional[LocalDispatch],
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
        local_dispatch = dispatch_module.dispatch
    return local_github_dispatch.call_with_machine_github_authorization(
        request,
        local_dispatch,
        core_available=dispatch_module is not None,
    )


def _enrich_https_function_drift(
    response: FunctionCallResponse,
    request: FunctionCallRequest,
    function_hint: Optional[HintResolver],
) -> FunctionCallResponse:
    if response.success or response.error is None:
        return response
    if response.error.code != "function_not_registered" or function_hint is None:
        return response
    hint = function_hint(request.function)
    if not hint:
        return response
    existing = response.error.recovery_hint or ""
    if hint in existing:
        return response
    joined = f"{hint}\n\n{existing}" if existing else hint
    return response.model_copy(
        update={"error": response.error.model_copy(update={"recovery_hint": joined})}
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


def _default_human_writer(response: FunctionCallResponse, stdout, stderr) -> None:
    if response.success:
        print(json.dumps(response.result, sort_keys=True), file=stdout)
        for warning in response.warnings:
            print(
                f"warning: {warning.code} ({warning.step}): {warning.detail}",
                file=stderr,
            )
        return
    if response.error is not None:
        print(f"error ({response.error.code}): {response.error.message}", file=stderr)
        if response.error.recovery_hint:
            print(f"hint: {response.error.recovery_hint}", file=stderr)
    else:
        print("error: dispatch returned success=False", file=stderr)


__all__ = [
    "build_actor",
    "build_request",
    "call_dispatcher",
    "emit_response",
    "response_to_dict",
]

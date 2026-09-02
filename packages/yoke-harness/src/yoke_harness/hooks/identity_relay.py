"""Relay identity fields derived from product-safe runtime probes."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from yoke_cli.config import machine_config
from yoke_contracts.session_execution import SUBAGENT_EXECUTION_PAYLOAD_KEY
from yoke_contracts.cursor_session_map import (
    CURSOR_CONVERSATION_ENV_VAR,
    CURSOR_SESSION_MAP_DIR_NAME,
    recorded_session_id_for_conversation,
)
from yoke_harness.hooks.identity_runtime import (
    _codex_resolve_entrypoint,
    cursor_surface_entrypoint,
    detect_entrypoint,
    is_claude,
    is_codex,
    is_cursor,
    resolve_session_id,
)
from yoke_harness.hooks.identity_observed import (
    client_executor_version,
    client_machine_id,
)
from yoke_harness.hooks.identity_claude_presentation import (
    observe_claude_presentation,
)
from yoke_harness.hooks.identity_model_facts import (
    REGISTRATION_EVENTS,
    client_model_facts,
    model_facts_settled,
    record_model_facts_shipped,
    resolve_model_facts,
)


_EXECUTOR_PREFIX = "executor_default_lane_"


def _normalize_config_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _normalize_prefix_token(prefix: str) -> str:
    folded = re.sub(r"[^a-z0-9]+", "_", prefix.strip().lower())
    return folded.lstrip("_")


def _routing_settings() -> dict[str, str]:
    cfg = machine_config.load_config()
    settings = cfg.get("settings")
    if not isinstance(settings, dict):
        return {}
    return {str(k): str(v) for k, v in settings.items()}


def client_lane(event_name: str, executor: str) -> Optional[str]:
    """Return the machine-config lane for ``executor``, or ``None``.

    ``None`` means "this client has no lane opinion" and is the answer
    whenever machine config declares no matching executor key — the common
    case, because routing policy normally lives in the project's
    ``session-routing`` capability, which only the server can read. Inventing
    a placeholder here instead would ship an explicit lane on the wire and
    overrule that project policy at registration.
    """
    if event_name not in REGISTRATION_EVENTS:
        return None
    try:
        token = _normalize_config_token(executor)
        exact: dict[str, str] = {}
        wildcards: dict[str, str] = {}
        for key, value in _routing_settings().items():
            if not key.startswith(_EXECUTOR_PREFIX) or not value:
                continue
            raw = key[len(_EXECUTOR_PREFIX) :]
            if "*" in raw:
                if raw.endswith("*"):
                    wildcards[_normalize_prefix_token(raw[:-1])] = value.strip()
            else:
                exact[_normalize_config_token(raw)] = value.strip()
        if token in exact:
            return exact[token]
        matched = None
        for prefix in wildcards:
            if token.startswith(prefix) and (
                matched is None
                or len(prefix) > len(matched)
                or (len(prefix) == len(matched) and prefix < matched)
            ):
                matched = prefix
        if matched is not None:
            return wildcards[matched]
        return exact.get("unknown") or None
    except Exception:
        return None


def client_entrypoint(executor: str, payload: dict[str, Any]) -> Optional[str]:
    """Resolve the client surface that relayed registration must preserve."""
    try:
        direct = payload.get("entrypoint")
        if is_claude(executor) and isinstance(direct, str) and direct.strip():
            return direct.strip()
        if is_codex(executor):
            sid = resolve_session_id(json.dumps(payload))
            return _codex_resolve_entrypoint(thread_id=sid or None) or None
        if is_cursor(executor):
            return cursor_surface_entrypoint()
        detected = detect_entrypoint()
        if detected:
            return detected
        return None
    except Exception:
        return None


def _workspace_path_candidates(payload: dict[str, Any]) -> list[str]:
    """Ordered workspace paths a hook payload may carry.

    ``workspace_roots`` (a list of absolute paths, first entry = the
    workspace the harness opened) leads because it names the harness
    workspace directly; the scalar keys follow for payloads that carry
    only a per-event directory.
    """
    candidates: list[str] = []
    roots = payload.get("workspace_roots")
    if isinstance(roots, list):
        candidates.extend(
            root for root in roots if isinstance(root, str) and root.strip()
        )
    for key in ("cwd", "workspace", "project_dir"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value)
    return candidates


def client_project_id(payload: dict[str, Any]) -> Optional[int]:
    for value in _workspace_path_candidates(payload):
        try:
            resolved = machine_config.project_id(Path(value))
        except Exception:
            continue
        if resolved is not None:
            return resolved
    return None


def client_native_thread_id(
    executor: str,
    yoke_session_id: str = "",
    payload: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Return the mapped harness-native identity for a Yoke session."""
    if is_codex(executor):
        value = os.environ.get("CODEX_THREAD_ID", "").strip()
        return value or None
    if is_cursor(executor):
        source = payload or {}
        if source.get(SUBAGENT_EXECUTION_PAYLOAD_KEY) is True:
            return None
        candidate = source.get("conversation_id")
        conversation_id = candidate.strip() if isinstance(candidate, str) else ""
        conversation_id = (
            conversation_id
            or os.environ.get(
                CURSOR_CONVERSATION_ENV_VAR,
                "",
            ).strip()
        )
        if not conversation_id:
            return None
        try:
            mapped = recorded_session_id_for_conversation(
                machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME,
                conversation_id,
            )
        except Exception:  # noqa: BLE001 — identity enrichment is best effort
            return None
        if not mapped or (yoke_session_id and mapped != yoke_session_id):
            return None
        return conversation_id
    if not is_claude(executor):
        return None
    native_session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    registered_id = yoke_session_id or os.environ.get("YOKE_SESSION_ID", "").strip()
    if native_session_id and registered_id and native_session_id != registered_id:
        return native_session_id
    return None


def relay_identity_payload(
    event_name: str,
    payload: dict[str, Any],
    executor: str,
) -> dict[str, Optional[str] | Optional[int]]:
    entrypoint = client_entrypoint(executor, payload)
    return {
        "entrypoint": entrypoint,
        **client_model_facts(event_name, payload, executor),
        "execution_lane": client_lane(event_name, executor),
        "project_id": client_project_id(payload),
        "executor_version": client_executor_version(executor, entrypoint),
        "machine_id": client_machine_id(),
        "native_thread_id": client_native_thread_id(
            executor,
            resolve_session_id(json.dumps(payload)),
            payload,
        ),
        **observe_claude_presentation(executor, payload),
    }


__all__ = [
    "REGISTRATION_EVENTS",
    "client_entrypoint",
    "client_executor_version",
    "client_lane",
    "client_machine_id",
    "client_model_facts",
    "model_facts_settled",
    "record_model_facts_shipped",
    "resolve_model_facts",
    "client_native_thread_id",
    "client_project_id",
    "relay_identity_payload",
]

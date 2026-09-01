"""Relay identity fields derived from product-safe runtime probes."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from yoke_cli.config import machine_config
from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.session_context_window_sources import records_window_separately
from yoke_contracts.session_model_facts import (
    MODEL_FACT_FIELDS,
    SessionModelFacts,
)
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


REGISTRATION_EVENTS = frozenset({"SessionStart", "UserPromptSubmit"})

_MODEL_SHIPPED_DIR_NAME = "relay-model-shipped"
_MODEL_SHIPPED_PRUNE_AGE_S = 7 * 86400
_EXECUTOR_PREFIX = "executor_default_lane_"


def _model_shipped_marker(session_id: str) -> Path:
    return machine_config.yoke_home() / _MODEL_SHIPPED_DIR_NAME / session_id


def _mark_model_shipped(session_id: str) -> None:
    try:
        marker = _model_shipped_marker(session_id)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        cutoff = time.time() - _MODEL_SHIPPED_PRUNE_AGE_S
        for entry in marker.parent.iterdir():
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
            except OSError:
                continue
    except Exception:
        return


def model_facts_settled(event_name: str, session_id: str) -> bool:
    """True when this session's model facts need not be resolved again.

    Resolution is not free — it reads a transcript or a conversation store,
    and on Claude it shells out for the parent's argv — so once a served
    model has actually been read the marker stops the work on every later
    hook event. Registration events always resolve, and a session whose
    artifact has not answered yet stays unmarked and keeps trying, which is
    the normal case for the first events of a run: the artifact naming the
    served model does not exist until the first turn completes.
    """
    if event_name in REGISTRATION_EVENTS:
        return False
    if not session_id:
        return True
    try:
        return _model_shipped_marker(session_id).exists()
    except Exception:
        return True


def resolve_model_facts(payload: dict[str, Any], executor: str) -> SessionModelFacts:
    """Resolve both halves of this session's model facts from the machine.

    The ask comes from the launch environment; the served truth comes from
    the harness's own artifact. Either half may be empty — an artifact that
    has not been written yet attests nothing — and neither ever stands in
    for the other.
    """
    try:
        from yoke_harness.model_attestation import attest_served_facts
        from yoke_harness.model_request import requested_facts

        transcript = payload.get("transcript_path")
        served = attest_served_facts(
            executor,
            payload,
            transcript_path=transcript if isinstance(transcript, str) else "",
        )
        asked = requested_facts(executor, payload)
    except Exception:  # noqa: BLE001 — identity probes never break a hook
        return SessionModelFacts()
    return SessionModelFacts(
        model=served.model,
        reasoning_effort=served.reasoning_effort,
        context_window_tokens=served.context_window_tokens,
        requested_model=asked.requested_model,
        requested_reasoning_effort=asked.requested_reasoning_effort,
        requested_context_window_tokens=asked.requested_context_window_tokens,
    )


def client_model_facts(
    event_name: str, payload: dict[str, Any], executor: str
) -> dict[str, Any]:
    """Model facts for the relayed wire, or ``{}`` once they are settled.

    Absent keys mean "nothing to say"; an explicit value is either what was
    asked or what a provider reported, never one standing in for the other.
    """
    session_id = payload.get("session_id")
    session_id = session_id if isinstance(session_id, str) else ""
    if model_facts_settled(event_name, session_id):
        return _recorded_window_facts(session_id, executor)
    facts = resolve_model_facts(payload, executor)
    if session_id and facts.model is not None:
        _mark_model_shipped(session_id)
    return {
        field: getattr(facts, field)
        for field in MODEL_FACT_FIELDS
        if getattr(facts, field) is not None
    }


def _recorded_window_facts(session_id: str, executor: str) -> dict[str, Any]:
    """The one served fact that can still arrive after a session settles.

    Settling ends the expensive reads, and it has to: a proven model is the
    whole answer a transcript or store will give. Claude's window is the
    exception — a different process writes it on its own schedule, after the
    model is known — so it is looked for past the settle point, affordable
    only because that lookup opens one small file rather than re-reading an
    artifact. A stored window resends harmlessly; the merge drops it.
    """
    try:
        if not records_window_separately(canonical_harness_id(executor)):
            return {}
        from yoke_harness.claude_status_line import recorded_context_window

        window = recorded_context_window(session_id)
    except Exception:  # noqa: BLE001 — identity probes never break a hook
        return {}
    return {"context_window_tokens": window} if window is not None else {}


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
    """Resolve the client's surface alias for the relayed registration.

    On an https machine this is the only entrypoint that reaches the server:
    the client-side register self-skips and the relayed server-side
    ensure-register owns the row. The executor argument names the family
    (the rendered hook command pins it), so Cursor resolves its surface
    from that rather than from ``detect_entrypoint``, whose Cursor branch
    needs env the IDE surface has not exported yet at sessionStart.
    """
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
) -> Optional[str]:
    """Return the harness-native identity for one registered Yoke session.

    Codex exports its thread directly. Cursor's conversation id is trusted
    only after the client hook map binds it to this Yoke session. Claude's
    native session is useful only when it differs from the Yoke identity.
    """
    if is_codex(executor):
        value = os.environ.get("CODEX_THREAD_ID", "").strip()
        return value or None
    if is_cursor(executor):
        conversation_id = os.environ.get(CURSOR_CONVERSATION_ENV_VAR, "").strip()
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
    "resolve_model_facts",
    "client_native_thread_id",
    "client_project_id",
    "relay_identity_payload",
]

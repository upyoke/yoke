"""Relay identity fields derived from product-safe runtime probes."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from yoke_cli.config import machine_config
from yoke_harness.hooks.identity_runtime import (
    _codex_resolve_entrypoint,
    _codex_resolve_model,
    _is_placeholder_model,
    detect_entrypoint,
    detect_model,
    is_codex,
    resolve_session_id,
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


def client_model(event_name: str, payload: dict[str, Any], executor: str) -> Optional[str]:
    session_id = payload.get("session_id")
    session_id = session_id if isinstance(session_id, str) else ""
    if event_name not in REGISTRATION_EVENTS:
        if not session_id:
            return None
        try:
            if _model_shipped_marker(session_id).exists():
                return None
        except Exception:
            return None
    try:
        if is_codex(executor):
            sid = resolve_session_id(json.dumps(payload))
            model = _codex_resolve_model(thread_id=sid or None) or ""
        else:
            tp = payload.get("transcript_path")
            model = detect_model(
                executor, transcript_path=tp if isinstance(tp, str) else "",
            )
        if _is_placeholder_model(model):
            return None
        if session_id:
            _mark_model_shipped(session_id)
        return model
    except Exception:
        return None


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
    if event_name not in REGISTRATION_EVENTS:
        return None
    try:
        token = _normalize_config_token(executor)
        exact: dict[str, str] = {}
        wildcards: dict[str, str] = {}
        for key, value in _routing_settings().items():
            if not key.startswith(_EXECUTOR_PREFIX) or not value:
                continue
            raw = key[len(_EXECUTOR_PREFIX):]
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
        return exact.get("unknown", "primary")
    except Exception:
        return None


def client_entrypoint(executor: str, payload: dict[str, Any]) -> Optional[str]:
    try:
        if is_codex(executor):
            sid = resolve_session_id(json.dumps(payload))
            return _codex_resolve_entrypoint(thread_id=sid or None) or None
        return detect_entrypoint() or None
    except Exception:
        return None


def client_project_id(payload: dict[str, Any]) -> Optional[int]:
    for key in ("cwd", "workspace", "project_dir"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            return machine_config.project_id(Path(value))
        except Exception:
            return None
    return None


def relay_identity_payload(
    event_name: str, payload: dict[str, Any], executor: str,
) -> dict[str, Optional[str] | Optional[int]]:
    return {
        "entrypoint": client_entrypoint(executor, payload),
        "model": client_model(event_name, payload, executor),
        "execution_lane": client_lane(event_name, executor),
        "project_id": client_project_id(payload),
    }


__all__ = [
    "REGISTRATION_EVENTS",
    "client_entrypoint",
    "client_lane",
    "client_model",
    "client_project_id",
    "relay_identity_payload",
]

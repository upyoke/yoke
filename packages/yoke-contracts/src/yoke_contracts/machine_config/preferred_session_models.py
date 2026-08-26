"""Preferred per-surface model for yoke-launched sessions.

One machine-local map in ``~/.yoke/config.json`` so every launcher
resolves the same default: explicit ``--model`` > this map > vendor default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

PREFERRED_SESSION_MODELS_KEY = "preferred_session_models"
VENDOR_DEFAULT_SOURCE = "vendor default"
EXPLICIT_SOURCE = "explicit --model"


@dataclass(frozen=True)
class ResolvedLaunchModel:
    model: str | None
    source: str


def preferred_session_models(payload: Mapping[str, Any] | None) -> dict[str, str]:
    """Return the cleaned surface-to-model map from a config payload."""
    raw = (payload or {}).get(PREFERRED_SESSION_MODELS_KEY)
    if not isinstance(raw, Mapping):
        return {}
    models: dict[str, str] = {}
    for key, value in raw.items():
        surface = str(key).strip()
        model = value.strip() if isinstance(value, str) else ""
        if surface and model:
            models[surface] = model
    return models


def validate_preferred_session_models(payload: Mapping[str, Any]) -> list[Any]:
    """Reject a present map that is not surface-name to model-id strings."""
    from yoke_contracts.machine_config.schema_projects import _error

    raw = payload.get(PREFERRED_SESSION_MODELS_KEY)
    if raw is None:
        return []
    if not isinstance(raw, Mapping):
        return [
            _error(
                "preferred_session_models_invalid",
                f"{PREFERRED_SESSION_MODELS_KEY} must be an object",
                path=PREFERRED_SESSION_MODELS_KEY,
            )
        ]
    issues = []
    for key, value in raw.items():
        surface = str(key).strip()
        if not surface:
            issues.append(
                _error(
                    "preferred_session_models_surface_invalid",
                    "preferred model surfaces must be non-empty strings",
                    path=PREFERRED_SESSION_MODELS_KEY,
                )
            )
            continue
        if not isinstance(value, str) or not value.strip():
            issues.append(
                _error(
                    "preferred_session_models_model_invalid",
                    f"{PREFERRED_SESSION_MODELS_KEY}.{surface} must be a non-empty model id",
                    path=f"{PREFERRED_SESSION_MODELS_KEY}.{surface}",
                )
            )
    return issues


def resolve_launch_model(
    explicit: str | None,
    surface: str,
    *,
    payload: Mapping[str, Any] | None = None,
) -> ResolvedLaunchModel:
    """Resolve the model a launcher should send for ``surface``."""
    model = (explicit or "").strip()
    if model:
        return ResolvedLaunchModel(model, EXPLICIT_SOURCE)
    mapping = preferred_session_models(payload) if payload is not None else _load_map()
    preferred = mapping.get((surface or "").strip())
    if preferred:
        return ResolvedLaunchModel(
            preferred, f"{PREFERRED_SESSION_MODELS_KEY}.{surface}"
        )
    return ResolvedLaunchModel(None, VENDOR_DEFAULT_SOURCE)


def list_preferred_models(surface: str | None = None) -> dict[str, Any]:
    """Name configured defaults and the config key they come from."""
    from yoke_contracts.machine_config.runtime import config_path

    mapping = _load_map()
    entries = [
        {
            "surface": name,
            "model": model,
            "source": f"{PREFERRED_SESSION_MODELS_KEY}.{name}",
        }
        for name, model in sorted(mapping.items())
    ]
    selected_surface = (surface or "").strip() or None
    selected = None
    if selected_surface:
        resolved = resolve_launch_model(
            None,
            selected_surface,
            payload={
                PREFERRED_SESSION_MODELS_KEY: mapping,
            },
        )
        selected = {
            "surface": selected_surface,
            "model": resolved.model,
            "source": resolved.source,
        }
    return {
        "key": PREFERRED_SESSION_MODELS_KEY,
        "config_file": str(config_path()),
        "entries": entries,
        "selected": selected,
    }


def render_list_models(report: Mapping[str, Any], *, json_mode: bool) -> str:
    """Render ``--list-models`` output, naming the default source."""
    import json

    if json_mode:
        return json.dumps(report, indent=2) + "\n"
    lines = [
        f"{report['key']} in {report['config_file']}",
    ]
    entries = report.get("entries") or []
    if not entries:
        lines.append("  (no preferred models configured)")
    for entry in entries:
        lines.append(f"  {entry['surface']}  {entry['model']}  ({entry['source']})")
    selected = report.get("selected")
    if isinstance(selected, Mapping):
        model = selected.get("model") or "(none)"
        lines.append(f"{selected['surface']} default: {model}")
        lines.append(f"source: {selected['source']}")
    return "\n".join(lines) + "\n"


def _load_map() -> dict[str, str]:
    from yoke_contracts.machine_config.runtime import load_config

    return preferred_session_models(load_config())


__all__ = [
    "EXPLICIT_SOURCE",
    "PREFERRED_SESSION_MODELS_KEY",
    "ResolvedLaunchModel",
    "VENDOR_DEFAULT_SOURCE",
    "list_preferred_models",
    "preferred_session_models",
    "render_list_models",
    "resolve_launch_model",
    "validate_preferred_session_models",
]

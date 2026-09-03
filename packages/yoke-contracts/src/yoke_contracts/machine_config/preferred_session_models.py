"""Structured per-surface defaults for Yoke-launched model selections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    model_catalog,
    validate_launch_model_selection,
)


PREFERRED_SESSION_MODELS_KEY = "preferred_session_models"
VENDOR_DEFAULT_SOURCE = "vendor default"
EXPLICIT_SOURCE = "explicit launch request"
_FIELDS = ("model", "reasoning_effort", "context_window_tokens")


@dataclass(frozen=True)
class ResolvedLaunchSelection:
    model: str | None
    reasoning_effort: str | None
    context_window_tokens: int | None
    sources: Mapping[str, str]

    def selection(self) -> LaunchModelSelection:
        return LaunchModelSelection(
            self.model,
            self.reasoning_effort,
            self.context_window_tokens,
        )

    def payload(self) -> dict[str, str | int]:
        return self.selection().payload()


def _clean_entry(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    model = value.get("model")
    effort = value.get("reasoning_effort")
    context = value.get("context_window_tokens")
    return {
        "model": model.strip() if isinstance(model, str) else model,
        "reasoning_effort": effort.strip().lower()
        if isinstance(effort, str)
        else effort,
        "context_window_tokens": context,
    }


def preferred_session_models(
    payload: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Return the normalized structured surface map from machine config."""
    raw = (payload or {}).get(PREFERRED_SESSION_MODELS_KEY)
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(surface).strip(): _clean_entry(entry)
        for surface, entry in raw.items()
        if str(surface).strip()
    }


def launchable_preferred_surfaces() -> tuple[str, ...]:
    from yoke_contracts.session_control.capabilities import (
        SESSION_SURFACE_CAPABILITIES,
    )

    return tuple(
        sorted(
            surface
            for surface, capability in SESSION_SURFACE_CAPABILITIES.items()
            if capability.create == "supported"
        )
    )


def _blank_entry() -> dict[str, Any]:
    return {
        "model": "",
        "reasoning_effort": "",
        "context_window_tokens": None,
    }


def blank_preferred_session_models() -> dict[str, dict[str, Any]]:
    return {surface: _blank_entry() for surface in launchable_preferred_surfaces()}


def seed_preferred_session_models(payload: dict[str, Any]) -> bool:
    if PREFERRED_SESSION_MODELS_KEY in payload:
        return False
    payload[PREFERRED_SESSION_MODELS_KEY] = blank_preferred_session_models()
    return True


def validate_preferred_session_models(payload: Mapping[str, Any]) -> list[Any]:
    """Require one structured model/effort/context entry per configured surface."""
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
    allowed = set(launchable_preferred_surfaces())
    issues = []
    for raw_surface, raw_entry in raw.items():
        surface = str(raw_surface).strip()
        path = f"{PREFERRED_SESSION_MODELS_KEY}.{surface or '<blank>'}"
        if surface not in allowed:
            issues.append(
                _error(
                    "preferred_session_models_surface_invalid",
                    f"{surface or '<blank>'} is not a launchable CLI surface",
                    path=path,
                )
            )
            continue
        if not isinstance(raw_entry, Mapping):
            issues.append(
                _error(
                    "preferred_session_models_entry_invalid",
                    f"{path} must be an object with model, reasoning_effort, "
                    "and context_window_tokens",
                    path=path,
                )
            )
            continue
        unknown = set(raw_entry) - set(_FIELDS)
        if unknown:
            issues.append(
                _error(
                    "preferred_session_models_field_invalid",
                    f"{path} has unknown fields: {', '.join(sorted(unknown))}",
                    path=path,
                )
            )
            continue
        entry = _clean_entry(raw_entry)
        if not isinstance(entry.get("model"), str):
            issues.append(
                _error(
                    "preferred_session_models_model_invalid",
                    f"{path}.model must be a string (blank means unset)",
                    path=f"{path}.model",
                )
            )
            continue
        if not isinstance(entry.get("reasoning_effort"), str):
            issues.append(
                _error(
                    "preferred_session_models_reasoning_effort_invalid",
                    f"{path}.reasoning_effort must be a string (blank means unset)",
                    path=f"{path}.reasoning_effort",
                )
            )
            continue
        context = entry.get("context_window_tokens")
        if context is not None and (
            isinstance(context, bool) or not isinstance(context, int) or context <= 0
        ):
            issues.append(
                _error(
                    "preferred_session_models_context_window_invalid",
                    f"{path}.context_window_tokens must be a positive integer or null",
                    path=f"{path}.context_window_tokens",
                )
            )
            continue
        try:
            validate_launch_model_selection(
                surface,
                LaunchModelSelection(
                    entry["model"] or None,
                    entry["reasoning_effort"] or None,
                    context,
                ),
            )
        except ValueError as exc:
            issues.append(
                _error(
                    getattr(exc, "code", "model_selection_invalid"),
                    str(exc),
                    path=path,
                )
            )
    return issues


def resolve_launch_selection(
    model: str | None,
    reasoning_effort: str | None,
    context_window_tokens: int | None,
    surface: str,
    *,
    payload: Mapping[str, Any] | None = None,
) -> ResolvedLaunchSelection:
    """Resolve every knob independently: explicit, configured, then vendor default."""
    mapping = preferred_session_models(payload) if payload is not None else _load_map()
    preferred = mapping.get(str(surface or "").strip(), {})
    explicit = {
        "model": str(model or "").strip() or None,
        "reasoning_effort": str(reasoning_effort or "").strip().lower() or None,
        "context_window_tokens": context_window_tokens,
    }
    selected: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for field in _FIELDS:
        configured = preferred.get(field)
        configured = configured if configured is not None and configured != "" else None
        if explicit[field] is not None:
            selected[field] = explicit[field]
            sources[field] = EXPLICIT_SOURCE
        elif configured is not None:
            selected[field] = configured
            sources[field] = f"{PREFERRED_SESSION_MODELS_KEY}.{surface}.{field}"
        else:
            selected[field] = None
            sources[field] = VENDOR_DEFAULT_SOURCE
    validated = validate_launch_model_selection(
        surface,
        LaunchModelSelection(
            selected["model"],
            selected["reasoning_effort"],
            selected["context_window_tokens"],
        ),
    )
    return ResolvedLaunchSelection(
        validated.model,
        validated.reasoning_effort,
        validated.context_window_tokens,
        sources,
    )


def list_preferred_models(surface: str | None = None) -> dict[str, Any]:
    """Return configured defaults beside each CLI's accepted launch catalog."""
    from yoke_contracts.machine_config.runtime import config_path

    mapping = _load_map()
    surfaces = (surface,) if surface else launchable_preferred_surfaces()
    catalogs = [model_catalog(item).to_dict() for item in surfaces]
    selected = None
    if surface:
        resolved = resolve_launch_selection(None, None, None, surface)
        selected = {
            "model": resolved.model,
            "reasoning_effort": resolved.reasoning_effort,
            "context_window_tokens": resolved.context_window_tokens,
            "surface": surface,
            "sources": dict(resolved.sources),
        }
    return {
        "key": PREFERRED_SESSION_MODELS_KEY,
        "config_file": str(config_path()),
        "entries": mapping,
        "selected": selected,
        "catalogs": catalogs,
    }


def _context_label(value: object) -> str:
    if value == 1_000_000:
        return "1m"
    return str(value) if value else "(none)"


def render_list_models(report: Mapping[str, Any], *, json_mode: bool) -> str:
    import json

    if json_mode:
        return json.dumps(report, indent=2) + "\n"
    lines = [f"{report['key']} in {report['config_file']}"]
    entries = report.get("entries") or {}
    if not entries:
        lines.append("  (no preferred selections configured)")
    for surface, entry in entries.items():
        if not isinstance(entry, Mapping):
            continue
        lines.append(
            f"  {surface}  model={entry.get('model') or '(none)'}  "
            f"effort={entry.get('reasoning_effort') or '(none)'}  "
            f"context={_context_label(entry.get('context_window_tokens'))}"
        )
    for catalog in report.get("catalogs") or ():
        lines.append(f"{catalog['surface']} accepted ({catalog['source']}):")
        if catalog.get("error"):
            lines.append(f"  unavailable: {catalog['error']}; verify the native CLI")
            continue
        lines.append(
            "  models: "
            + (", ".join(catalog.get("models") or ()) or "(vendor default only)")
        )
        lines.append(
            "  effort: "
            + (", ".join(catalog.get("effort_levels") or ()) or "(unsupported)")
        )
        contexts = [
            _context_label(value) for value in catalog.get("context_windows") or ()
        ]
        lines.append("  context: " + (", ".join(contexts) or "(unsupported)"))
    return "\n".join(lines) + "\n"


def _load_map() -> dict[str, dict[str, Any]]:
    from yoke_contracts.machine_config.runtime import load_config

    return preferred_session_models(load_config())


__all__ = [
    "EXPLICIT_SOURCE",
    "PREFERRED_SESSION_MODELS_KEY",
    "ResolvedLaunchSelection",
    "VENDOR_DEFAULT_SOURCE",
    "blank_preferred_session_models",
    "launchable_preferred_surfaces",
    "list_preferred_models",
    "preferred_session_models",
    "render_list_models",
    "resolve_launch_selection",
    "seed_preferred_session_models",
    "validate_preferred_session_models",
]

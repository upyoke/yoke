"""Rollout-safe per-surface defaults for Yoke-launched model selections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_contracts.machine_config.preferred_session_model_config import (
    PREFERRED_SESSION_MODELS_KEY,
    PREFERRED_SESSION_REASONING_EFFORTS_KEY,
    blank_preferred_session_models,
    blank_preferred_session_reasoning_efforts,
    configured_preferred_selection,
    launchable_preferred_surfaces,
    preferred_session_models,
    preferred_session_reasoning_efforts,
    seed_preferred_session_models,
    validate_preferred_session_models,
)
from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    model_catalog,
    validate_launch_model_selection,
)
from yoke_contracts.session_model_facts import CLAUDE_CONTEXT_TIER_TOKENS


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


def resolve_launch_selection(
    model: str | None,
    reasoning_effort: str | None,
    context_window_tokens: int | None,
    surface: str,
    *,
    payload: Mapping[str, Any] | None = None,
) -> ResolvedLaunchSelection:
    """Resolve each knob independently: explicit, configured, vendor default."""
    configured, configured_sources = configured_preferred_selection(
        payload if payload is not None else _load_payload(),
        surface,
    )
    explicit = LaunchModelSelection(
        str(model or "").strip() or None,
        str(reasoning_effort or "").strip().lower() or None,
        context_window_tokens,
    )
    selected: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for field in _FIELDS:
        explicit_value = getattr(explicit, field)
        configured_value = getattr(configured, field)
        if explicit_value is not None:
            selected[field] = explicit_value
            sources[field] = EXPLICIT_SOURCE
        elif configured_value is not None:
            selected[field] = configured_value
            sources[field] = configured_sources[field]
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

    payload = _load_payload()
    surfaces = (surface,) if surface else launchable_preferred_surfaces()
    entries = {
        item: resolve_launch_selection(None, None, None, item, payload=payload).payload()
        for item in surfaces
    }
    selected = None
    if surface:
        resolved = resolve_launch_selection(None, None, None, surface, payload=payload)
        selected = {
            "model": resolved.model,
            "reasoning_effort": resolved.reasoning_effort,
            "context_window_tokens": resolved.context_window_tokens,
            "surface": surface,
            "sources": dict(resolved.sources),
        }
    return {
        "key": PREFERRED_SESSION_MODELS_KEY,
        "effort_key": PREFERRED_SESSION_REASONING_EFFORTS_KEY,
        "config_file": str(config_path()),
        "entries": entries,
        "selected": selected,
        "catalogs": [model_catalog(item).to_dict() for item in surfaces],
    }


def _context_label(value: object) -> str:
    if value == CLAUDE_CONTEXT_TIER_TOKENS:
        return "1m"
    return str(value) if value else "(none)"


def render_list_models(report: Mapping[str, Any], *, json_mode: bool) -> str:
    import json

    if json_mode:
        return json.dumps(report, indent=2) + "\n"
    lines = [
        f"{report['key']} in {report['config_file']}",
        f"effort defaults: {report['effort_key']}",
    ]
    for surface, entry in (report.get("entries") or {}).items():
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


def _load_payload() -> dict[str, Any]:
    from yoke_contracts.machine_config.runtime import load_config

    return load_config()


__all__ = [
    "EXPLICIT_SOURCE",
    "PREFERRED_SESSION_MODELS_KEY",
    "PREFERRED_SESSION_REASONING_EFFORTS_KEY",
    "ResolvedLaunchSelection",
    "VENDOR_DEFAULT_SOURCE",
    "blank_preferred_session_models",
    "blank_preferred_session_reasoning_efforts",
    "launchable_preferred_surfaces",
    "list_preferred_models",
    "preferred_session_models",
    "preferred_session_reasoning_efforts",
    "render_list_models",
    "resolve_launch_selection",
    "seed_preferred_session_models",
    "validate_preferred_session_models",
]

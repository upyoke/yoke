"""Rollout-safe per-surface defaults for Yoke-launched model selections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

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
from yoke_contracts.session_model_facts import CLAUDE_CONTEXT_TIER_TOKENS

if TYPE_CHECKING:
    from yoke_contracts.session_control.model_selection import LaunchModelSelection


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
        from yoke_contracts.session_control.model_selection import LaunchModelSelection

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
    from yoke_contracts.session_control.model_selection import (
        LaunchModelSelection,
        validate_launch_model_selection,
    )

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


def list_preferred_models(
    surface: str | None = None,
    *,
    availability: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return configured defaults beside each surface's observed availability.

    ``availability`` is this machine's native model readings, which the caller
    supplies because observing them means running vendor binaries — work that
    belongs to the relay rather than to a configuration reader.
    """
    from yoke_contracts.machine_config.runtime import config_path
    from yoke_contracts.session_control.model_selection import (
        SURFACE_CONTEXT_WINDOWS,
        SURFACE_EFFORT_LEVELS,
    )

    payload = _load_payload()
    surfaces = (surface,) if surface else launchable_preferred_surfaces()
    entries = {
        item: resolve_launch_selection(
            None, None, None, item, payload=payload
        ).payload()
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
        # What each surface's flags accept is the same on every machine, so it
        # is declared. Which models it can select is not, so that is observed.
        "accepted": {
            item: {
                "reasoning_efforts": list(SURFACE_EFFORT_LEVELS.get(item, ())),
                "context_windows": list(SURFACE_CONTEXT_WINDOWS.get(item, ())),
            }
            for item in surfaces
        },
        "availability": [
            dict(
                (availability or {}).get(item) or {"surface": item, "status": "unknown"}
            )
            for item in surfaces
        ],
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
    for surface, accepted in (report.get("accepted") or {}).items():
        lines.append(f"{surface} accepted by the CLI flags:")
        lines.append(
            "  effort: "
            + (", ".join(accepted.get("reasoning_efforts") or ()) or "(unsupported)")
        )
        contexts = [
            _context_label(value) for value in accepted.get("context_windows") or ()
        ]
        lines.append("  context: " + (", ".join(contexts) or "(unsupported)"))
    for reading in report.get("availability") or ():
        source = reading.get("source") or "not observed"
        lines.append(
            f"{reading['surface']} available ({reading.get('status')}, {source}):"
        )
        if reading.get("reason"):
            lines.append(f"  {reading['reason']}")
        models = [
            str(entry.get("model"))
            for entry in reading.get("models") or ()
            if entry.get("model")
        ]
        if models:
            lines.append(
                f"  observed {reading.get('observed_at') or 'at an unknown time'}"
            )
            lines.append("  models: " + ", ".join(models))
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

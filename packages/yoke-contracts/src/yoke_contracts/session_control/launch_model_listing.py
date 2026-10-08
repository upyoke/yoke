"""What each launch surface on this machine accepts and can select.

``--list-models`` answers the question a person composing an explicit launch
asks: which efforts and context windows does this surface's CLI take, and
which models does it say it can run right now. The first is declared, because
the flags are the same on every machine; the second is observed, because it
depends on the provider account behind the surface.

Which model a launch *should* use is not answered here. Level options decide
that (``yoke universe levels get``); an explicit ``--model`` overrides them.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_model_facts import CLAUDE_CONTEXT_TIER_TOKENS


def launchable_surfaces() -> tuple[str, ...]:
    """Every surface Yoke can create a session on, sorted."""
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


def list_launch_models(
    surface: str | None = None,
    *,
    availability: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return each surface's accepted flags beside its observed availability.

    ``availability`` is this machine's native model readings, which the caller
    supplies because observing them means running vendor binaries -- work that
    belongs to the relay rather than to a listing.
    """
    from yoke_contracts.session_control.model_selection import (
        SURFACE_CONTEXT_WINDOWS,
        SURFACE_EFFORT_LEVELS,
    )

    surfaces = (surface,) if surface else launchable_surfaces()
    return {
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


def render_launch_models(report: Mapping[str, Any], *, json_mode: bool) -> str:
    import json

    if json_mode:
        return json.dumps(report, indent=2) + "\n"
    lines = [
        "Launch models are chosen by level options (`yoke universe levels get`); "
        "--model overrides them for one launch."
    ]
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


__all__ = ["launchable_surfaces", "list_launch_models", "render_launch_models"]

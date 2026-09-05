"""Manifest projection of each CLI launch model-selection contract."""

from __future__ import annotations

from yoke_contracts.session_control.model_selection import (
    DOCUMENTED_MODELS,
    SURFACE_CONTEXT_WINDOWS,
    SURFACE_EFFORT_LEVELS,
    resume_selection_mode,
)


_ENCODING = {
    "claude-cli": {
        "model": "--model MODEL",
        "reasoning_effort": "--effort EFFORT",
        "context_window_tokens": "--model MODEL[1m]",
    },
    "codex-cli": {
        "model": "--model MODEL",
        "reasoning_effort": "-c model_reasoning_effort=EFFORT",
        "context_window_tokens": None,
    },
    "cursor-cli": {
        "model": "--model MODEL",
        "reasoning_effort": "--model 'MODEL[effort=EFFORT]'",
        "context_window_tokens": "--model 'MODEL[context=1m]'",
    },
}


def launch_model_selection_manifest(surface: str) -> dict[str, object]:
    """Return machine-readable accepted knobs and native encodings."""
    return {
        "source": "yoke_contracts.session_control.model_selection",
        "surface": surface,
        "model_catalog": ("native_cli" if surface == "cursor-cli" else "documented"),
        "documented_models": list(DOCUMENTED_MODELS.get(surface, ())),
        "reasoning_efforts": list(SURFACE_EFFORT_LEVELS.get(surface, ())),
        "context_windows": list(SURFACE_CONTEXT_WINDOWS.get(surface, ())),
        "native_encoding": _ENCODING.get(surface, {}),
        "resume_selection": resume_selection_mode(surface),
    }


__all__ = ["launch_model_selection_manifest"]

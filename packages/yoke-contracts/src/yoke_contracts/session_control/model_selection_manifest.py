"""Manifest projection of each CLI launch model-selection contract."""

from __future__ import annotations

from yoke_contracts.session_control.model_selection import (
    SURFACE_CONTEXT_WINDOWS,
    SURFACE_EFFORT_LEVELS,
    resume_selection_mode,
)
from yoke_contracts.session_control.native_model_parsers import (
    CODEX_LIST_SOURCE,
    CURSOR_LIST_SOURCE,
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

#: How each surface's selectable models are discovered. The manifest names the
#: route rather than a list of model ids, because which models an account can
#: select is a per-machine observation the relay reports and a document
#: rendered at build time can only be wrong about.
_MODEL_DISCOVERY = {
    "codex-cli": CODEX_LIST_SOURCE,
    "cursor-cli": CURSOR_LIST_SOURCE,
}


def launch_model_selection_manifest(surface: str) -> dict[str, object]:
    """Return machine-readable accepted knobs and native encodings."""
    discovery = _MODEL_DISCOVERY.get(surface)
    return {
        "source": "yoke_contracts.session_control.model_selection",
        "surface": surface,
        "model_discovery": discovery or "none",
        "model_catalog": "native_cli" if discovery else "unobserved",
        "reasoning_efforts": list(SURFACE_EFFORT_LEVELS.get(surface, ())),
        "context_windows": list(SURFACE_CONTEXT_WINDOWS.get(surface, ())),
        "native_encoding": _ENCODING.get(surface, {}),
        "resume_selection": resume_selection_mode(surface),
    }


__all__ = ["launch_model_selection_manifest"]

"""Typed launch model selection shared by control plane, CLI, and relays.

This module owns what a CLI *flag* will accept — the model token grammar, the
effort levels each surface parses, the context-window encodings. Which models
an account can actually select is a different question with a different
answer per machine, and it is observed natively rather than declared here;
see :mod:`yoke_contracts.session_control.native_models`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Mapping, Sequence

from yoke_contracts.session_control.native_model_parsers import (
    CURSOR_EFFORT_LEVELS,
    cursor_token_effort,
)
from yoke_contracts.session_model_facts import (
    CLAUDE_CONTEXT_TIER_SUFFIX,
    CLAUDE_CONTEXT_TIER_TOKENS,
)


_CONTEXT_TOKEN = re.compile(r"^([1-9][0-9]*)([km]?)$", re.IGNORECASE)
_MODEL_TOKEN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*$")

SURFACE_EFFORT_LEVELS: Mapping[str, tuple[str, ...]] = {
    "claude-cli": ("low", "medium", "high", "max"),
    "codex-cli": (
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "ultra",
    ),
    "cursor-cli": CURSOR_EFFORT_LEVELS,
}
SURFACE_CONTEXT_WINDOWS: Mapping[str, tuple[int, ...]] = {
    "claude-cli": (CLAUDE_CONTEXT_TIER_TOKENS,),
    "codex-cli": (),
    "cursor-cli": (),  # Context is model-specific native availability, not a flag.
}
ResumeSelectionMode = Literal["native", "explicit"]
RESUME_SELECTION_MODES: Mapping[str, ResumeSelectionMode] = {
    "claude-cli": "native",
    "codex-cli": "explicit",
    "cursor-cli": "explicit",
}


def resume_selection_mode(surface: str) -> ResumeSelectionMode | None:
    """Name how a supported CLI keeps model selection across resume.

    Native surfaces restore the conversation's latest selection themselves.
    Explicit surfaces re-send the current attested selection because their
    ambient configuration would otherwise be consulted again.
    """
    return RESUME_SELECTION_MODES.get(surface)


class LaunchModelSelectionError(ValueError):
    """A model knob cannot be expressed by the requested harness surface."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LaunchModelSelection:
    model: str | None = None
    reasoning_effort: str | None = None
    context_window_tokens: int | None = None

    def payload(self) -> dict[str, str | int]:
        return {
            key: value
            for key, value in (
                ("model", self.model),
                ("reasoning_effort", self.reasoning_effort),
                ("context_window_tokens", self.context_window_tokens),
            )
            if value is not None
        }


def parse_context_window_tokens(value: object) -> int:
    """Parse a positive token count, accepting compact CLI forms such as 1m."""
    if isinstance(value, bool):
        raise ValueError("context window must be a positive token count")
    token = str(value or "").strip().lower()
    match = _CONTEXT_TOKEN.fullmatch(token)
    if match is None:
        raise ValueError("context window must be a positive integer, Nk, or Nm")
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000}[match.group(2)]
    return int(match.group(1)) * multiplier


def validate_launch_model_selection(
    surface: str,
    selection: LaunchModelSelection,
    *,
    accepted_models: Sequence[str] | None = None,
) -> LaunchModelSelection:
    """Reject knobs a surface cannot pass without silently dropping them."""
    prefix = surface.replace("-cli", "").replace("-", "_")
    model = str(selection.model or "").strip() or None
    effort = str(selection.reasoning_effort or "").strip().lower() or None
    context = selection.context_window_tokens
    if model and (_MODEL_TOKEN.fullmatch(model) is None or len(model) > 160):
        raise LaunchModelSelectionError(
            f"{prefix}_model_invalid",
            f"{surface} model must be one bounded CLI model token; use an exact "
            "native model listing selector and pass supported knobs separately",
        )
    levels = SURFACE_EFFORT_LEVELS.get(surface, ())
    if effort and effort not in levels:
        raise LaunchModelSelectionError(
            f"{prefix}_reasoning_effort_unsupported",
            f"{surface} does not accept reasoning effort {effort!r}; "
            f"accepted: {', '.join(levels) or 'none'}",
        )
    windows = SURFACE_CONTEXT_WINDOWS.get(surface, ())
    if context is not None and surface != "cursor-cli" and context not in windows:
        raise LaunchModelSelectionError(
            f"{prefix}_context_window_unsupported",
            f"{surface} does not accept a {context}-token context window; "
            f"accepted: {', '.join(str(item) for item in windows) or 'none'}; "
            "omit --context-window or choose a supported window",
        )
    if surface in {"claude-cli", "cursor-cli"} and context and not model:
        raise LaunchModelSelectionError(
            f"{prefix}_model_required_for_context_window",
            f"{surface} needs --model to express --context-window",
        )
    if surface == "cursor-cli" and effort and not model:
        raise LaunchModelSelectionError(
            "cursor_model_required_for_reasoning_effort",
            "cursor-cli needs --model to express --reasoning-effort",
        )
    if surface == "cursor-cli" and model and effort:
        encoded = cursor_token_effort(model)
        if encoded and encoded != effort:
            raise LaunchModelSelectionError(
                "cursor_reasoning_effort_conflict",
                f"cursor-cli selector {model!r} encodes {encoded!r}, which "
                f"conflicts with {effort!r}; omit --reasoning-effort or choose "
                "the published selector for the intended effort",
            )
    if accepted_models is not None and model:
        exact = set(accepted_models)
        if model not in exact:
            raise LaunchModelSelectionError(
                f"{prefix}_model_unsupported",
                f"{surface} did not publish model {model!r}; refresh this "
                "machine's native availability with "
                "`yoke relay probe-models --surface "
                f"{surface}`",
            )
    return LaunchModelSelection(model, effort, context)


def native_model_selector(surface: str, selection: LaunchModelSelection) -> str | None:
    """Render the provider-specific model token after validation."""
    selected = validate_launch_model_selection(surface, selection)
    if not selected.model:
        return None
    if surface == "claude-cli" and selected.context_window_tokens:
        return f"{selected.model}{CLAUDE_CONTEXT_TIER_SUFFIX}"
    if surface == "cursor-cli" and selected.reasoning_effort:
        if not cursor_token_effort(selected.model):
            base = selected.model.removesuffix("-fast")
            speed = "-fast" if selected.model.endswith("-fast") else ""
            return f"{base}-{selected.reasoning_effort}{speed}"
    return selected.model


__all__ = [
    "LaunchModelSelection",
    "LaunchModelSelectionError",
    "RESUME_SELECTION_MODES",
    "ResumeSelectionMode",
    "SURFACE_CONTEXT_WINDOWS",
    "SURFACE_EFFORT_LEVELS",
    "native_model_selector",
    "parse_context_window_tokens",
    "resume_selection_mode",
    "validate_launch_model_selection",
]

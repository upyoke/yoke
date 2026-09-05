"""Typed launch model selection shared by control plane, CLI, and relays."""

from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
import subprocess
from typing import Callable, Literal, Mapping, Sequence

from yoke_contracts.harness_cli_manifest import harness_cli_manifest
from yoke_contracts.session_model_facts import (
    CLAUDE_CONTEXT_TIER_SUFFIX,
    CLAUDE_CONTEXT_TIER_TOKENS,
)


_CONTEXT_TOKEN = re.compile(r"^([1-9][0-9]*)([km]?)$", re.IGNORECASE)
_MODEL_LINE = re.compile(r"^([a-zA-Z0-9][a-zA-Z0-9._-]*)\s+-\s+(.+)$")
_MODEL_TOKEN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*$")
_CURSOR_EFFORT_LEVELS = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "extra-high",
    "max",
)
_EFFORT_SUFFIXES = tuple(sorted(_CURSOR_EFFORT_LEVELS, key=len, reverse=True))

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
    "cursor-cli": _CURSOR_EFFORT_LEVELS,
}
SURFACE_CONTEXT_WINDOWS: Mapping[str, tuple[int, ...]] = {
    "claude-cli": (CLAUDE_CONTEXT_TIER_TOKENS,),
    "codex-cli": (),
    "cursor-cli": (CLAUDE_CONTEXT_TIER_TOKENS,),
}
DOCUMENTED_MODELS: Mapping[str, tuple[str, ...]] = {
    "claude-cli": (
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5",
    ),
    "codex-cli": (
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "gpt-5.4",
    ),
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


@dataclass(frozen=True)
class ModelCatalog:
    surface: str
    models: tuple[str, ...]
    effort_levels: tuple[str, ...]
    context_windows: tuple[int, ...]
    source: str
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, object]:
        return {
            "surface": self.surface,
            "models": list(self.models),
            "effort_levels": list(self.effort_levels),
            "context_windows": list(self.context_windows),
            "source": self.source,
            "available": self.available,
            "error": self.error,
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
            f"{surface} model must be one bounded CLI model token",
        )
    levels = SURFACE_EFFORT_LEVELS.get(surface, ())
    if effort and effort not in levels:
        raise LaunchModelSelectionError(
            f"{prefix}_reasoning_effort_unsupported",
            f"{surface} does not accept reasoning effort {effort!r}; "
            f"accepted: {', '.join(levels) or 'none'}",
        )
    windows = SURFACE_CONTEXT_WINDOWS.get(surface, ())
    if context is not None and context not in windows:
        raise LaunchModelSelectionError(
            f"{prefix}_context_window_unsupported",
            f"{surface} does not accept a {context}-token context window; "
            f"accepted: {', '.join(str(item) for item in windows) or 'none'}",
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
    if accepted_models is not None and model:
        exact = set(accepted_models)
        base_is_published = any(item.startswith(f"{model}-") for item in exact)
        if model not in exact and not base_is_published:
            raise LaunchModelSelectionError(
                f"{prefix}_model_unsupported",
                f"{surface} did not publish model {model!r}; rerun --list-models",
            )
    return LaunchModelSelection(model, effort, context)


def native_model_selector(surface: str, selection: LaunchModelSelection) -> str | None:
    """Render the provider-specific model token after validation."""
    selected = validate_launch_model_selection(surface, selection)
    if not selected.model:
        return None
    if surface == "claude-cli" and selected.context_window_tokens:
        return f"{selected.model}{CLAUDE_CONTEXT_TIER_SUFFIX}"
    if surface == "cursor-cli" and (
        selected.reasoning_effort or selected.context_window_tokens
    ):
        parameters: list[str] = []
        if selected.context_window_tokens:
            parameters.append("context=1m")
        if selected.reasoning_effort:
            parameters.append(f"effort={selected.reasoning_effort}")
        return f"{selected.model}[{','.join(parameters)}]"
    return selected.model


def _cursor_effort(model: str) -> str | None:
    token = model.removesuffix("-fast")
    for effort in _EFFORT_SUFFIXES:
        if token.endswith(f"-{effort}"):
            return effort
    return None


def parse_cursor_model_catalog(output: str) -> ModelCatalog:
    """Parse only model rows from Cursor's human ``--list-models`` answer."""
    rows = []
    efforts: set[str] = set()
    for raw in str(output or "").splitlines():
        match = _MODEL_LINE.fullmatch(raw.strip())
        if match is None:
            continue
        model, _label = match.groups()
        rows.append(model)
        effort = _cursor_effort(model)
        if effort:
            efforts.add(effort)
    error = None if rows else "cursor-agent returned no parseable model rows"
    return ModelCatalog(
        "cursor-cli",
        tuple(dict.fromkeys(rows)),
        tuple(level for level in _CURSOR_EFFORT_LEVELS if level in efforts),
        SURFACE_CONTEXT_WINDOWS["cursor-cli"],
        "cursor-agent --list-models",
        error,
    )


CatalogRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run_catalog_command(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )


def model_catalog(
    surface: str,
    *,
    runner: CatalogRunner = _run_catalog_command,
) -> ModelCatalog:
    """Return provider-published models where available, documented facts otherwise."""
    if surface != "cursor-cli":
        return ModelCatalog(
            surface,
            DOCUMENTED_MODELS.get(surface, ()),
            SURFACE_EFFORT_LEVELS.get(surface, ()),
            SURFACE_CONTEXT_WINDOWS.get(surface, ()),
            "documented CLI contract",
            (
                None
                if surface in DOCUMENTED_MODELS
                else "surface has no launch model contract"
            ),
        )
    executable = harness_cli_manifest("cursor").executable
    resolved = shutil.which(executable)
    if not resolved:
        return ModelCatalog(
            surface,
            (),
            (),
            (),
            "cursor-agent --list-models",
            "cursor-agent not found",
        )
    try:
        completed = runner((resolved, "--list-models"))
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        return ModelCatalog(
            surface,
            (),
            (),
            (),
            "cursor-agent --list-models",
            type(exc).__name__,
        )
    if completed.returncode != 0:
        return ModelCatalog(
            surface,
            (),
            (),
            (),
            "cursor-agent --list-models",
            f"exit {completed.returncode}",
        )
    return parse_cursor_model_catalog(completed.stdout)


__all__ = [
    "DOCUMENTED_MODELS",
    "LaunchModelSelection",
    "LaunchModelSelectionError",
    "ModelCatalog",
    "RESUME_SELECTION_MODES",
    "ResumeSelectionMode",
    "SURFACE_CONTEXT_WINDOWS",
    "SURFACE_EFFORT_LEVELS",
    "model_catalog",
    "native_model_selector",
    "parse_context_window_tokens",
    "parse_cursor_model_catalog",
    "resume_selection_mode",
    "validate_launch_model_selection",
]

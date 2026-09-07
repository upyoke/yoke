"""Validate effective launch selections against one machine's native listing."""

from __future__ import annotations

import re
from typing import Any, Mapping

from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    LaunchModelSelectionError,
    native_model_selector,
    parse_context_window_tokens,
    validate_launch_model_selection,
)
from yoke_contracts.session_control.native_model_parsers import (
    cursor_selector_without_effort,
    cursor_token_effort,
)


def resolve_observed_model_selection(
    surface: str,
    selection: LaunchModelSelection,
    reading: Mapping[str, Any] | None,
) -> LaunchModelSelection:
    """Resolve only advertised variants; an absent observation proves nothing."""
    selected = validate_launch_model_selection(surface, selection)
    if not selected.model:
        return selected
    reading = reading or {}
    models = {
        entry["model"]: entry
        for entry in reading.get("models", ())
        if reading.get("status") in {"ok", "stale"} and entry.get("model")
    }
    recovery = f"refresh with `yoke relay probe-models --surface {surface}`"
    if not models:
        if surface == "cursor-cli" and (
            selected.reasoning_effort or selected.context_window_tokens is not None
        ):
            raise LaunchModelSelectionError(
                "cursor_model_availability_unknown",
                "cursor-cli cannot verify this effort/context combination without "
                f"a native model observation; {recovery} and preview again",
            )
        return selected
    if surface == "cursor-cli":
        model = native_model_selector(surface, selected)
        if selected.reasoning_effort and not cursor_token_effort(selected.model):
            candidates = [
                token
                for token, entry in models.items()
                if cursor_selector_without_effort(token) == selected.model
                and selected.reasoning_effort in entry.get("reasoning_efforts", ())
            ]
            if len(candidates) == 1:
                model = candidates[0]
        selected = LaunchModelSelection(
            model,
            selected.reasoning_effort,
            selected.context_window_tokens,
        )
    selected = validate_launch_model_selection(
        surface, selected, accepted_models=tuple(models)
    )
    entry = models[selected.model]
    if selected.reasoning_effort and selected.reasoning_effort not in entry.get(
        "reasoning_efforts", ()
    ):
        raise LaunchModelSelectionError(
            f"{surface.removesuffix('-cli')}_reasoning_effort_unsupported",
            f"{surface} did not publish effort {selected.reasoning_effort!r} for "
            f"{selected.model!r}; choose an advertised effort or omit it; {recovery}",
        )
    if surface == "cursor-cli" and selected.context_window_tokens is not None:
        # Display labels describe a selectable window, never a served-session fact.
        windows = {
            parse_context_window_tokens(token)
            for token in re.findall(
                r"\b[1-9][0-9]*[kKmM]\b", entry.get("description", "")
            )
        }
        if selected.context_window_tokens not in windows:
            raise LaunchModelSelectionError(
                "cursor_context_window_unsupported",
                f"cursor-cli did not publish a {selected.context_window_tokens}-token "
                f"window for {selected.model!r}; omit --context-window or choose "
                f"a variant whose native listing names that window; {recovery}",
            )
    return selected


__all__ = ["resolve_observed_model_selection"]

"""Typed Cursor requests and provider-specific model selector rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    native_model_selector,
)
from yoke_contracts.session_model_facts import effort_suffix_of
from yoke_harness.session_relay_runtime import (
    RelayExecutionContext,
    WakeMode,
    normalize_wake_mode,
)


def cursor_model_selector(context: RelayExecutionContext) -> str | None:
    selection = LaunchModelSelection(
        context.requested_model,
        context.requested_reasoning_effort,
        context.requested_context_window_tokens,
    )
    if context.job_kind == "wake":
        return _resume_model_selector(selection)
    return native_model_selector("cursor-cli", selection)


def _resume_model_selector(selection: LaunchModelSelection) -> str | None:
    """Replay stored native selectors without duplicating their parameters.

    Cursor attests both flat variants and bracketed selectors. A flat variant
    already describes its complete parameter combination; bracketed forms
    replace only separately attested knobs and retain every other parameter.
    Launch requests retain their stricter, separate-knob validation.
    """
    model = str(selection.model or "").strip()
    if not model:
        return None
    if "[" not in model or not model.endswith("]"):
        flat_model = model.removesuffix("-fast")
        effort = effort_suffix_of(flat_model)
        if effort:
            if selection.reasoning_effort:
                flat_model = flat_model[: -len(effort)] + selection.reasoning_effort
            return native_model_selector(
                "cursor-cli",
                LaunchModelSelection(
                    flat_model + ("-fast" if model.endswith("-fast") else "")
                ),
            )
        return native_model_selector("cursor-cli", selection)
    base, _, encoded = model.partition("[")
    override = native_model_selector(
        "cursor-cli",
        LaunchModelSelection(
            base, selection.reasoning_effort, selection.context_window_tokens
        ),
    )
    if override == base:
        return model
    parameters = encoded[:-1].split(",")
    for parameter in override[len(base) + 1 : -1].split(","):
        key = parameter.partition("=")[0]
        for index, current in enumerate(parameters):
            if current.partition("=")[0].strip() == key:
                if current.strip() != parameter:
                    parameters[index] = parameter
                break
        else:
            parameters.append(parameter)
    return f"{base}[{','.join(parameters)}]"


@dataclass(frozen=True)
class CursorCreateRequest:
    """One opaque create request; the attestation is never printable."""

    checkout: Path
    launch_id: str
    surface_version: str
    native_instruction: str = field(repr=False)
    launch_attestation: str = field(repr=False)
    requested_model: str | None = None


@dataclass(frozen=True)
class CursorWakeRequest:
    """One exact-session resume with the current session's model selector.

    Print-mode turns do not persist Cursor's last-used-model metadata, and
    parameter restoration uses shared configuration. The control plane sends
    the current session selection explicitly, including any supported knobs.
    """

    checkout: Path
    target_session_id: str
    surface_version: str
    target_liveness: str | None
    wake_mode: WakeMode
    native_instruction: str = field(repr=False)
    requested_model: str | None = None
    attempt_id: str = ""
    lease_id: str = ""

    def __post_init__(self) -> None:
        if normalize_wake_mode(self.wake_mode) is None:
            raise ValueError("wake instruction has no authorized mode")


__all__ = [
    "CursorCreateRequest",
    "CursorWakeRequest",
    "cursor_model_selector",
]

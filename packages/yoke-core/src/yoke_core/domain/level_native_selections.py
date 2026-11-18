"""Expand model/effort rows only into selectors observed on a native surface."""

from dataclasses import dataclass
from yoke_contracts.harness_cli_manifest import HARNESS_CLI_MANIFESTS
from yoke_contracts.model_level_resolution import normalized_effort
from yoke_contracts.model_reference import lookup_model_reference
from yoke_contracts.session_control.model_selection_manifest import (
    launch_model_selection_manifest,
)
from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    LaunchModelSelectionError,
    validate_launch_model_selection,
)
from yoke_contracts.session_control.native_model_parsers import cursor_token_effort


@dataclass(frozen=True)
class NativeLevelSelection:
    surface: str
    model: str
    reasoning_effort: str
    context_window_tokens: int | None = None


def catalog_supports(surface, model, records):
    """Exclude providers the surface's manifest cannot serve."""
    record = lookup_model_reference(model, records).record
    providers = launch_model_selection_manifest(surface)["model_providers"]
    return record is None or providers is None or record.provider in providers


def model_not_offered_reason(model, surface, reading):
    """Name the installed build whose listing lacks this level option's model.

    No older model stands in, and Yoke never runs the update itself: the
    option stays blocked until the operator updates that CLI and its own
    listing offers the model.
    """
    version = reading.get("surface_version") or "(version unreported)"
    machine = reading.get("machine") or "this machine"
    update = next(
        (m.update_command for m in HARNESS_CLI_MANIFESTS if m.surface_id == surface),
        "",
    )
    step = f"run `{update}` there" if update else f"update {surface} there"
    return (
        f"native_model_not_offered: {surface} {version} on {machine} does not "
        f"list {model}; {step}, then `yoke relay probe-models --surface {surface}`"
    )


def native_selections(entry, *, surface, reading, records):
    """Resolve the manifest's catalog or native selection at minimum effort."""
    if not catalog_supports(surface, entry.model, records):
        return (), None
    required = lookup_model_reference(entry.model, records).record
    if required is None:
        return (
            (),
            f"model_catalog_missing: {entry.model}; publish researched model facts with yoke models publish",
        )
    reading = reading or {}
    if launch_model_selection_manifest(surface)["model_catalog"] == "researched":
        reading = {
            "status": "ok",
            "models": [
                {
                    "model": required.model_id,
                    "reasoning_efforts": required.reasoning_efforts,
                }
            ],
        }
    if reading.get("status") == "unsupported":
        return (
            (),
            f"native_models_unsupported: {reading.get('reason') or 'no native listing adapter'}; ask the control-plane operator to provide this surface's listing adapter, or choose a surface with observed models",
        )
    if reading.get("status") not in {"ok", "stale"}:
        return (
            (),
            f"native_models_{reading.get('status', 'unknown')}: {reading.get('reason') or 'no native listing observed'}; refresh with yoke relay probe-models --surface {surface}",
        )
    if not any(
        lookup_model_reference(str(model.get("model") or ""), records).record
        == required
        for model in reading.get("models", ())
    ):
        return (), model_not_offered_reason(entry.model, surface, reading)
    if entry.min_effort not in {
        normalized_effort(value) for value in required.reasoning_efforts
    }:
        return (
            (),
            f"model_effort_unpublished: {entry.model} at {entry.min_effort}; publish researched effort facts with yoke models publish",
        )
    matched = []
    for native in reading.get("models", ()):
        token = str(native.get("model") or "")
        record = lookup_model_reference(token, records).record
        if record is None or record.model_id != required.model_id:
            continue
        efforts = native.get("reasoning_efforts") or (cursor_token_effort(token),)
        effort = next(
            (
                str(value)
                for value in efforts
                if normalized_effort(value) == entry.min_effort
            ),
            None,
        )
        if effort is None:
            continue
        try:
            selected = validate_launch_model_selection(
                surface, LaunchModelSelection(token, effort, None)
            )
        except LaunchModelSelectionError:
            continue
        matched.append(
            NativeLevelSelection(surface, selected.model, selected.reasoning_effort)
        )
    return (
        tuple(matched),
        None
        if matched
        else f"native_model_effort_unavailable: {entry.model} at {entry.min_effort} is not offered on {surface}; refresh the native listing or choose another level",
    )

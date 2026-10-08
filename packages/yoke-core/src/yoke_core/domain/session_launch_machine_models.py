"""Resolve a launch's model selection on the machine that will run it.

A launch carries an explicit selection: the option its level placement chose,
or the exact values the caller named. Any knob left unnamed falls to the
surface's own vendor default. The chosen machine then checks the selection
against what its surface last said it can run, because a model the provider
account behind that machine cannot select would launch a session that never
registers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    LaunchModelSelectionError,
    validate_launch_model_selection,
)
from yoke_contracts.session_control.native_models import sanitize_native_models
from yoke_contracts.session_control.observed_model_selection import (
    resolve_observed_model_selection,
)
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.session_launch_types import SessionLaunchError

#: Where a knob came from when the caller named it for this one launch.
EXPLICIT_SOURCE = "explicit launch request"
#: Where a knob came from when nobody named it.
VENDOR_DEFAULT_SOURCE = "vendor default"
_FIELDS = ("model", "reasoning_effort", "context_window_tokens")


@dataclass(frozen=True)
class ResolvedMachineSelection:
    """The effective launch selection and the source of each independent knob."""

    model: str | None
    reasoning_effort: str | None
    context_window_tokens: int | None
    sources: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "context_window_tokens": self.context_window_tokens,
            "model_source": self.sources["model"],
            "reasoning_effort_source": self.sources["reasoning_effort"],
            "context_window_source": self.sources["context_window_tokens"],
        }


def _cell(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return row[index]


def _decode_document(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    try:
        return json_helper.loads_text(raw)
    except (TypeError, ValueError):
        return {}


def machine_native_models(conn: Any, *, machine_id: str) -> dict[str, dict[str, Any]]:
    """Return what each surface on this machine last said it can select.

    Keyed by surface. Every entry names its own ``status``: only ``ok`` and
    ``stale`` carry observed models, and neither ``unknown`` nor
    ``unsupported`` is evidence that a model is unavailable — they say the
    machine has not answered and that Yoke has no listing route for that
    surface. A caller routing work reads the status before the list.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT surface_native_models FROM session_relays "
        f"WHERE machine_id = {marker} "
        "ORDER BY last_seen_at DESC, relay_id ASC",
        (str(machine_id),),
    ).fetchone()
    if row is None:
        return {}
    return sanitize_native_models(
        _decode_document(_cell(row, "surface_native_models", 0))
    )


def resolve_machine_selection(
    conn: Any,
    *,
    requested_model: str | None,
    requested_reasoning_effort: str | None,
    requested_context_window_tokens: int | None,
    machine_id: str | None,
    surface: str,
    explicit_source: str = EXPLICIT_SOURCE,
) -> ResolvedMachineSelection:
    """Resolve the named knobs over vendor defaults on the selected machine.

    ``explicit_source`` names where the named knobs came from, so a level
    launch reports its level option rather than an explicit request.
    """
    explicit = LaunchModelSelection(
        str(requested_model or "").strip() or None,
        str(requested_reasoning_effort or "").strip().lower() or None,
        requested_context_window_tokens,
    )
    sources = {
        field: explicit_source
        if getattr(explicit, field) is not None
        else VENDOR_DEFAULT_SOURCE
        for field in _FIELDS
    }
    try:
        selected = validate_launch_model_selection(surface, explicit)
        if machine_id:
            selected = resolve_observed_model_selection(
                surface,
                selected,
                machine_native_models(conn, machine_id=machine_id).get(surface),
            )
    except LaunchModelSelectionError as exc:
        raise SessionLaunchError(exc.code, str(exc)) from exc
    return ResolvedMachineSelection(
        model=selected.model,
        reasoning_effort=selected.reasoning_effort,
        context_window_tokens=selected.context_window_tokens,
        sources=sources,
    )


__all__ = [
    "EXPLICIT_SOURCE",
    "ResolvedMachineSelection",
    "VENDOR_DEFAULT_SOURCE",
    "machine_native_models",
    "resolve_machine_selection",
]

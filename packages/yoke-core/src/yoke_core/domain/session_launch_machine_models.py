"""Resolve a launch's model selection on the machine that will run it.

A launch executes on the chosen machine, so every default comes from that
machine's advertised preferences -- not the config on whichever machine
composed the request. The requester's config can name models and effort levels
that the target machine's provider account cannot use.

Each explicit launch knob still wins independently. This module joins those
explicit values to the selected machine's model, effort, and encoded context
defaults and returns the exact effective selection the relay must carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_contracts.machine_config.preferred_session_models import (
    EXPLICIT_SOURCE,
    PREFERRED_SESSION_MODELS_KEY,
    PREFERRED_SESSION_REASONING_EFFORTS_KEY,
    VENDOR_DEFAULT_SOURCE,
    resolve_launch_selection,
)
from yoke_contracts.session_control.model_selection import (
    LaunchModelSelectionError,
)
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.session_relay_types import (
    advertised_session_models,
    advertised_session_reasoning_efforts,
)


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


def machine_preference_payload(conn: Any, *, machine_id: str) -> dict[str, Any]:
    """Read the model and effort maps from one latest heartbeat."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT preferred_session_models, preferred_session_reasoning_efforts "
        "FROM session_relays "
        f"WHERE machine_id = {marker} "
        "ORDER BY last_seen_at DESC, relay_id ASC",
        (str(machine_id),),
    ).fetchone()
    if row is None:
        return {
            PREFERRED_SESSION_MODELS_KEY: {},
            PREFERRED_SESSION_REASONING_EFFORTS_KEY: {},
        }
    return {
        PREFERRED_SESSION_MODELS_KEY: advertised_session_models(
            _decode_document(_cell(row, "preferred_session_models", 0))
        ),
        PREFERRED_SESSION_REASONING_EFFORTS_KEY: (
            advertised_session_reasoning_efforts(
                _decode_document(_cell(row, "preferred_session_reasoning_efforts", 1))
            )
        ),
    }


def machine_preferred_models(conn: Any, *, machine_id: str) -> dict[str, str]:
    """Return the model selectors from the machine's latest heartbeat."""
    return dict(
        machine_preference_payload(conn, machine_id=machine_id)[
            PREFERRED_SESSION_MODELS_KEY
        ]
    )


def machine_preferred_reasoning_efforts(
    conn: Any, *, machine_id: str
) -> dict[str, str]:
    """Return the effort defaults from the machine's latest heartbeat."""
    return dict(
        machine_preference_payload(conn, machine_id=machine_id)[
            PREFERRED_SESSION_REASONING_EFFORTS_KEY
        ]
    )


def resolve_machine_selection(
    conn: Any,
    *,
    requested_model: str | None,
    requested_reasoning_effort: str | None,
    requested_context_window_tokens: int | None,
    machine_id: str | None,
    surface: str,
) -> ResolvedMachineSelection:
    """Resolve explicit knobs over defaults advertised by the selected machine."""
    payload = (
        machine_preference_payload(conn, machine_id=machine_id) if machine_id else {}
    )
    try:
        resolved = resolve_launch_selection(
            requested_model,
            requested_reasoning_effort,
            requested_context_window_tokens,
            surface,
            payload=payload,
        )
    except LaunchModelSelectionError as exc:
        raise SessionLaunchError(exc.code, str(exc)) from exc
    sources = {
        field: (
            source
            if source in {EXPLICIT_SOURCE, VENDOR_DEFAULT_SOURCE}
            else f"{machine_id} {source}"
        )
        for field, source in resolved.sources.items()
    }
    return ResolvedMachineSelection(
        model=resolved.model,
        reasoning_effort=resolved.reasoning_effort,
        context_window_tokens=resolved.context_window_tokens,
        sources=sources,
    )


__all__ = [
    "ResolvedMachineSelection",
    "machine_preference_payload",
    "machine_preferred_models",
    "machine_preferred_reasoning_efforts",
    "resolve_machine_selection",
]

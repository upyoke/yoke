"""Resolve a launch's model against the machine that will run it.

A launch executes on the chosen machine, so the default model it falls back
to is that machine's ``preferred_session_models`` -- not the map configured on
whichever machine composed the request. The requester's own config would name
a model the target machine may not even have installed, and the session would
start on a default nobody chose.

Explicit still wins: a model named on the launch request is passed through
unchanged. This module only answers what an unnamed model resolves to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.machine_config.preferred_session_models import (
    PREFERRED_SESSION_MODELS_KEY,
    VENDOR_DEFAULT_SOURCE,
)
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.session_relay_types import advertised_session_models


EXPLICIT_REQUEST_SOURCE = "explicit launch request"


@dataclass(frozen=True)
class ResolvedMachineModel:
    """The model a launch will carry, and the machine fact that decided it."""

    model: str | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "model_source": self.source}


def _cell(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return row[index]


def machine_preferred_models(conn: Any, *, machine_id: str) -> dict[str, str]:
    """Read the surface-to-model map the machine's own relay advertised."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT preferred_session_models FROM session_relays "
        f"WHERE machine_id = {marker} "
        "ORDER BY last_seen_at DESC, relay_id ASC",
        (str(machine_id),),
    ).fetchone()
    if row is None:
        return {}
    raw = _cell(row, "preferred_session_models", 0)
    if isinstance(raw, str):
        try:
            raw = json_helper.loads_text(raw)
        except (TypeError, ValueError):
            return {}
    return advertised_session_models(raw)


def resolve_machine_model(
    conn: Any,
    *,
    requested_model: str | None,
    machine_id: str | None,
    surface: str,
) -> ResolvedMachineModel:
    """Prefer an explicit model, then the chosen machine's own default."""
    explicit = str(requested_model or "").strip()
    if explicit:
        return ResolvedMachineModel(explicit, EXPLICIT_REQUEST_SOURCE)
    if not machine_id:
        return ResolvedMachineModel(None, VENDOR_DEFAULT_SOURCE)
    preferred = machine_preferred_models(conn, machine_id=machine_id).get(
        str(surface or "").strip()
    )
    if not preferred:
        return ResolvedMachineModel(None, VENDOR_DEFAULT_SOURCE)
    return ResolvedMachineModel(
        preferred,
        f"{machine_id} {PREFERRED_SESSION_MODELS_KEY}.{surface}",
    )


__all__ = [
    "EXPLICIT_REQUEST_SOURCE",
    "ResolvedMachineModel",
    "machine_preferred_models",
    "resolve_machine_model",
]

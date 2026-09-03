"""A machine's report that one session's native turn is already over.

Posture is normally a hook fact: the harness fires a turn-end hook, the
hook runner stamps ``waiting``, and the wake router reads that posture to
choose the stopped-session native resume. A turn that ends without firing
that hook says nothing, so its posture stays ``running`` indefinitely and
every wake for it resolves an operation its surface does not support.

The native's own turn record settles it, and only the machine that ran the
native can read that record. So the control plane names the sessions whose
wake is stuck, the relay reads those sessions' turn records, and the report
comes back here — the same shape as the relay's process-death report, for
the same reason: local evidence about a fact the control plane cannot see.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.harness_turn_record_capability import turn_record_surfaces


#: Surfaces whose native keeps a turn record a machine can read back.
#: Derived from the per-harness turn-record capability rather than listed
#: here, so a harness that declares a record — and the one that declares
#: why it needs none — is described in exactly one place.
NATIVE_TURN_RECORD_SURFACES = turn_record_surfaces()

#: What an observed turn end stamps: exactly the posture the missing hook
#: would have stamped, so the wake router needs no branch of its own.
NATIVE_TURN_END_POSTURE = "waiting"


class RelayTurnEndProbe(BaseModel):
    """One session the control plane asks this machine to read back."""

    model_config = ConfigDict(extra="ignore")
    session_id: str
    executor_surface: str


class RelayNativeTurnEnd(BaseModel):
    """One session whose native record proves its turn already ended."""

    model_config = ConfigDict(extra="forbid")
    session_id: str
    observed_at: str
    evidence: Dict[str, Any] = Field(default_factory=dict)


class RelayTurnEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relay_id: str
    machine_id: str
    projects: List[int]
    turn_ends: List[RelayNativeTurnEnd] = Field(default_factory=list, max_length=100)


class RelayTurnEndResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    reclassified: List[str] = Field(default_factory=list)
    skipped: List[Dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "NATIVE_TURN_END_POSTURE",
    "NATIVE_TURN_RECORD_SURFACES",
    "RelayNativeTurnEnd",
    "RelayTurnEndProbe",
    "RelayTurnEndRequest",
    "RelayTurnEndResponse",
]

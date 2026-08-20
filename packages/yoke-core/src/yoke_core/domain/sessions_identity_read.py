"""The one projection of a session row into resolved identity.

Registration resolves a session's identity once — canonical executor id and
display alias, provider, model, the execution lane the project's routing
policy maps that executor to, workspace, project, and actor — and writes it
to ``harness_sessions``. Every later consumer reads it back through here.

The lane is the field that makes this a single-reader contract rather than a
convenience. An offer still honours a caller-supplied lane — that is the
deliberate operator re-route, recorded as
``SessionOfferLaneOverrideApplied`` — which is precisely why nothing
automated may resolve one. A lane derived locally outranks the project's
``session-routing`` mapping, and two identical sessions in one checkout
proved the cost: the one whose shell variables happened to be empty passed
nothing, fell through to the stored row, and was routed correctly; the one
that substituted its locally guessed lane had every frontier item filtered
by a lane name the project declares no paths for. Reading identity in one
place, and sending none of it back, is what makes that non-determinism
unreachable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, List, Optional

from yoke_core.domain import db_backend


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


#: Refusal text for a session id the authority has no row for. Hooks
#: register every session at start and re-register on any later hook event,
#: so a missing row is a hook-installation fact — never a cue to substitute
#: a locally detected value.
UNREGISTERED_RECOVERY = (
    "Sessions register at start through the harness hooks. Check this "
    "project's hook installation with `yoke doctor run --quick`, or "
    "register explicitly with `yoke sessions begin --executor E "
    "--provider P --model M --workspace W`."
)


@dataclass(frozen=True)
class SessionIdentity:
    """Resolved identity as stored, with no locally derived field."""

    session_id: str
    executor: str
    executor_display_name: Optional[str]
    provider: str
    model: str
    workspace: str
    execution_lane: str
    capabilities: List[str] = field(default_factory=list)
    project_id: Optional[int] = None
    actor_id: Optional[int] = None
    mode: Optional[str] = None
    ended_at: Optional[str] = None


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _capabilities(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(entry) for entry in raw]
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if isinstance(parsed, list):
        return [str(entry) for entry in parsed]
    return []


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_session_identity(conn: Any, session_id: str) -> SessionIdentity:
    """Read *session_id*'s stored identity, or raise ``SessionError``.

    Raises:
        SessionError: ``NO_SESSION`` when the authority holds no row for
            this id. The message names the registration recovery; callers
            must not fall back to locally detected values.
    """
    from yoke_core.domain.sessions import SessionError

    row = conn.execute(
        "SELECT executor, executor_display_name, provider, model, workspace, "
        "execution_lane, capabilities, project_id, actor_id, mode, ended_at "
        f"FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError(
            "NO_SESSION",
            f"No session row for '{session_id}' on this control plane. "
            f"{UNREGISTERED_RECOVERY}",
        )
    return SessionIdentity(
        session_id=session_id,
        executor=_text(row[0]),
        executor_display_name=(
            str(row[1]) if row[1] is not None else None
        ),
        provider=_text(row[2]),
        model=_text(row[3]),
        workspace=_text(row[4]),
        execution_lane=_text(row[5]),
        capabilities=_capabilities(row[6]),
        project_id=_optional_int(row[7]),
        actor_id=_optional_int(row[8]),
        mode=(str(row[9]) if row[9] is not None else None),
        ended_at=(str(row[10]) if row[10] is not None else None),
    )


__all__ = [
    "UNREGISTERED_RECOVERY",
    "SessionIdentity",
    "resolve_session_identity",
]

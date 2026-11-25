"""Require a Yoke-launched CLI worker for a fresh QA walk."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.qa_case_starting_state import declares_starting_state
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    live_plan_execution_id,
    marker,
    select_plan_execution,
)


_WALK_LAUNCH_PREFIX = "qa-walk:"

WALK_LAUNCH_GUIDANCE = (
    "Run command-only partitions yourself and run lane cases from their lane. "
    "Launch each free walk in an itemless CLI session. See "
    ".yoke/docs/verification/walking.md#launch-a-walker."
)

_WALK_LAUNCH_RECOVERY = (
    "Read `yoke qa plan partitions <subject flags>`. "
    "Run command-only partitions and eligible lane cases from the owing session. "
    "For each free walk, pipe its instructions to "
    "`yoke session-control launch create --project P --level LEVEL --surface SURFACE "
    "--raw-instructions --stdin --idempotency-key qa-walk:SUBJECT:SCOPE:KEY:ATTEMPT` "
    "without --item. Use the subject item's requested launch level, or your own "
    "level for a group or standalone plan. Give the walker the subject flags, "
    "--partition KEY, frozen source when required, and the report route. "
    "If no relay has capacity, staff a relay machine serving claude-cli, "
    "codex-cli or cursor-cli. Follow .yoke/docs/verification/walking.md#launch-a-walker"
)



class QaWalkNeedsLaunchedSession(QaPlanExecutionStateError):
    code = "qa_walk_needs_launched_session"


def _is_walk(roster: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        declares_starting_state(case) or case.get("verdict_path") != "automatic"
        for case in roster
    )


def require_scoped_walk_launch(
    conn: Any,
    roster: Sequence[Mapping[str, Any]],
    *,
    session_id: str,
    execution_target_digest: str,
    group_id: str = "",
    **scope: Any,
) -> None:
    """Preserve a scoped execution the same session can already resume."""
    if not _is_walk(roster):
        return
    execution_id = live_plan_execution_id(
        conn,
        **scope,
        session_id=session_id,
        execution_target_digest=execution_target_digest,
        group_id=group_id,
    )
    if execution_id is not None:
        execution = select_plan_execution(conn, execution_id, lock=False)
        if execution.get("session_id") == session_id:
            return
    _require_registered_walk_launch(conn, session_id)


def require_walk_launch(
    conn: Any, roster: Sequence[Mapping[str, Any]], *, session_id: str
) -> None:
    """Check launch authority before freezing a new standalone walk roster."""
    if _is_walk(roster):
        _require_registered_walk_launch(conn, session_id)


def _require_registered_walk_launch(conn: Any, session_id: str) -> None:
    param = marker(conn)
    launch = query_one(
        conn,
        "SELECT 1 FROM session_launches "
        f"WHERE registered_session_id = {param} AND item_id IS NULL "
        f"AND SUBSTR(idempotency_key, 1, {param}) = {param} LIMIT 1",
        (session_id, len(_WALK_LAUNCH_PREFIX), _WALK_LAUNCH_PREFIX),
    )
    if launch is not None:
        return
    raise QaWalkNeedsLaunchedSession(
        compose_refusal(
            f"{QaWalkNeedsLaunchedSession.code}: fresh QA walks require an itemless QA walker launch",
            recovery=_WALK_LAUNCH_RECOVERY,
        )
    )

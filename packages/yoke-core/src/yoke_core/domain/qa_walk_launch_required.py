"""Require a Yoke-launched CLI worker for a fresh QA walk."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.qa_case_starting_state import is_host_command, needs_test_machine
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError, marker


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


def require_walk_launch(
    conn: Any, roster: Sequence[Mapping[str, Any]], *, session_id: str
) -> None:
    """Check launch authority before freezing a new walk roster."""
    if not any(
        needs_test_machine(case)
        or is_host_command(case)
        or case.get("verdict_path", "automatic") != "automatic"
        for case in roster
    ):
        return
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

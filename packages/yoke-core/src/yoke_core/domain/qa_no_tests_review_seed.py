"""The gate an attested no-tests project gets instead of a command case.

A project with no registered verification command reaches its review
transition with no plan attached, so nothing materializes and the QA gate
passes on an empty requirement set. That vacuous pass is worse than a failure:
it reports green for a review nobody performed.

When a project has attested it has no suite, the honest substitute is a
blocking implementation review — a human or agent reads the change against the
item, and records a verdict. This module seeds exactly that, at the same
transition the registered ``quick`` command would have attached to, so an
attested project's gate lands where an unattested project's gate lands.

Seeding is idempotent per item and transition. A re-entered transition finds
the requirement it wrote the first time and leaves it alone, because a second
row would double the review a reviewer has to satisfy for one change.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now, query_one
from yoke_core.domain.project_verification_posture import (
    attestation_reason,
    attests_no_tests,
)

#: The requirement kind a reviewer satisfies through the ordinary review
#: recording path. Not a QA method — there is no runner for it, which is
#: exactly why this is a direct requirement rather than a plan case.
NO_TESTS_REVIEW_QA_KIND = "implementation_review"

#: The registered scope whose transition this seed borrows. Reading the
#: transition from that scope's policy rather than naming a stage literally is
#: what makes the seeded requirement land where the command case would have:
#: if the scope's preferred stage ever moves, both move together.
SUBSTITUTED_COMMAND_SCOPE = "quick"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def review_transition_for_workflow(conn: Any, workflow_id: str) -> Optional[str]:
    """The stage the substituted ``quick`` command would have attached to."""
    from yoke_core.domain.qa_command_plan_registration import (
        COMMAND_SCOPE_POLICIES,
        policy_transitions,
    )

    policy = COMMAND_SCOPE_POLICIES[SUBSTITUTED_COMMAND_SCOPE]
    return policy_transitions(conn, policy).get(str(workflow_id))


def _existing_requirement_id(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
) -> Optional[int]:
    marker = _p(conn)
    row = query_one(
        conn,
        "SELECT id FROM qa_requirements "
        f"WHERE item_id={marker} AND qa_kind={marker} "
        f"AND workflow_transition_id={marker} AND plan_id IS NULL",
        (int(item_id), NO_TESTS_REVIEW_QA_KIND, str(transition_id)),
    )
    return int(row["id"]) if row is not None else None


def _success_policy(reason: str) -> str:
    detail = f" The operator attested: {reason}" if reason else ""
    return (
        "This project has no registered verification command, so the change "
        "is reviewed against the item's spec and acceptance criteria instead "
        f"of run.{detail}"
    )


def ensure_no_tests_review_requirement(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
) -> Optional[int]:
    """Seed the review requirement for an attested project, once.

    Returns the requirement id when one exists after the call, or ``None``
    when the item's project has not attested and nothing was seeded. Runs in
    the caller's transaction so it commits with the transition that triggered
    it.
    """
    marker = _p(conn)
    item = query_one(
        conn,
        f"SELECT project_id, workflow_id FROM items WHERE id={marker}",
        (int(item_id),),
    )
    if item is None:
        return None
    if not attests_no_tests(conn, int(item["project_id"])):
        return None
    expected = review_transition_for_workflow(conn, str(item["workflow_id"]))
    if expected is None or expected != str(transition_id):
        return None
    existing = _existing_requirement_id(
        conn,
        item_id=int(item_id),
        transition_id=str(transition_id),
    )
    if existing is not None:
        return existing
    reason = attestation_reason(conn, int(item["project_id"]))
    row = conn.execute(
        "INSERT INTO qa_requirements("
        "item_id, qa_kind, qa_phase, blocking_mode, requirement_source, "
        "success_policy, workflow_transition_id, created_at"
        f") VALUES ({', '.join([marker] * 8)}) RETURNING id",
        (
            int(item_id),
            NO_TESTS_REVIEW_QA_KIND,
            "verification",
            "blocking",
            "seeded_default",
            _success_policy(reason),
            str(transition_id),
            iso8601_now(),
        ),
    ).fetchone()
    return int(row["id"] if hasattr(row, "keys") else row[0])


__all__ = [
    "NO_TESTS_REVIEW_QA_KIND",
    "SUBSTITUTED_COMMAND_SCOPE",
    "ensure_no_tests_review_requirement",
    "review_transition_for_workflow",
]

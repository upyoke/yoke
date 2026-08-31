"""The explicit floor verdict a project gets instead of a command case.

A project with no registered verification command reaches its review
transition with no plan attached. The QA gate refuses that empty requirement
set as `GATE_QA_REQUIREMENTS_EMPTY`; this floor supplies the explicit evidence
that lets the transition proceed honestly.

The honest substitute is a blocking ``no_tests_declared`` requirement. An
agent reads the change against the item and records a verdict whose stored
kind says exactly what happened; no passing row implies that tests ran. This
module seeds that floor at the same transition the registered ``quick``
command would have attached to.

Seeding is idempotent per item and transition. A re-entered transition finds
the requirement it wrote the first time and leaves it alone, because a second
row would double the review a reviewer has to satisfy for one change.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now, query_one, query_scalar
from yoke_core.domain.project_verification_posture import (
    REGISTERED_COMMAND_PLAN_PREFIX,
    attestation_reason,
    attests_no_tests,
)
from yoke_core.domain.qa_plan_attachments import (
    workflow_uses_project_testing_defaults,
)

#: The requirement kind a reviewer satisfies through the ordinary review
#: recording path. Not a QA method — there is no runner for it, which is
#: exactly why this is a direct requirement rather than a plan case.
NO_TESTS_DECLARED_QA_KIND = "no_tests_declared"
NO_TESTS_DECLARED_VERDICT_LABEL = "agent-attested / no-tests-declared"

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
        (int(item_id), NO_TESTS_DECLARED_QA_KIND, str(transition_id)),
    )
    return int(row["id"]) if row is not None else None


def _has_registered_command(conn: Any, project_id: int) -> bool:
    marker = _p(conn)
    count = query_scalar(
        conn,
        "SELECT COUNT(*) FROM qa_plans "
        f"WHERE project_id={marker} AND retired_at IS NULL "
        f"AND substr(slug, 1, {len(REGISTERED_COMMAND_PLAN_PREFIX)})={marker}",
        (int(project_id), REGISTERED_COMMAND_PLAN_PREFIX),
    )
    return bool(count)


def _success_policy(*, project: str, reason: str, attested: bool) -> str:
    detail = f" The operator attested: {reason}" if reason else ""
    register = (
        f"yoke qa registered-command set --project {project} --scope quick "
        "--command <argv>"
    )
    if attested:
        register = (
            f"yoke qa no-tests clear --project {project} --reason <suite-added> "
            f"&& {register}"
        )
    return (
        f"{NO_TESTS_DECLARED_VERDICT_LABEL}: this project has no registered "
        "verification command. Review the change against the item's spec and "
        f"record a passing agent verdict with qa_kind={NO_TESTS_DECLARED_QA_KIND}; "
        f"that verdict does not claim tests ran.{detail} Raise to executed "
        f"tests in one line: `{register}`."
    )


def ensure_no_tests_review_requirement(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
) -> Optional[int]:
    """Seed the no-command floor requirement for a project, once.

    Returns the requirement id when one exists after the call, or ``None``
    when the pinned workflow does not consume project testing defaults or a
    registered command exists. Runs in the caller's transaction so it commits
    with the transition that triggered it.
    """
    marker = _p(conn)
    item = query_one(
        conn,
        "SELECT i.project_id, i.workflow_id, p.slug AS project "
        "FROM items i JOIN projects p ON p.id=i.project_id "
        f"WHERE i.id={marker}",
        (int(item_id),),
    )
    if item is None:
        return None
    if not workflow_uses_project_testing_defaults(conn, int(item_id)):
        return None
    if _has_registered_command(conn, int(item["project_id"])):
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
    attested = attests_no_tests(conn, int(item["project_id"]))
    row = conn.execute(
        "INSERT INTO qa_requirements("
        "item_id, qa_kind, qa_phase, blocking_mode, requirement_source, "
        "success_policy, workflow_transition_id, created_at"
        f") VALUES ({', '.join([marker] * 8)}) RETURNING id",
        (
            int(item_id),
            NO_TESTS_DECLARED_QA_KIND,
            "verification",
            "blocking",
            "seeded_default",
            _success_policy(
                project=str(item["project"]),
                reason=reason,
                attested=attested,
            ),
            str(transition_id),
            iso8601_now(),
        ),
    ).fetchone()
    return int(row["id"] if hasattr(row, "keys") else row[0])


__all__ = [
    "NO_TESTS_DECLARED_QA_KIND",
    "NO_TESTS_DECLARED_VERDICT_LABEL",
    "SUBSTITUTED_COMMAND_SCOPE",
    "ensure_no_tests_review_requirement",
    "review_transition_for_workflow",
]

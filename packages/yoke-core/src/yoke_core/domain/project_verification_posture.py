"""Reading and writing a project's attestation that it has no test suite.

A project either has a verification command bound as its gate or it has
attested that there is nothing to bind. Both are honest answers; holding both
at once is not, because the review transition would then seed a command case
*and* a review requirement for the same item, and the next boot's registered
command convergence would walk into a registration the attestation forbids.

So the two declarations are made mutually exclusive here, at the write. The
attestation retires the project's registered command plans in the same
transaction that records it, and registration refuses while the attestation
stands (see :mod:`yoke_core.domain.qa_command_plan_registration`). Neither
surface has to tolerate a state the other one can no longer create.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.verification_posture import (
    POSTURE_ATTESTED_NO_TESTS,
    POSTURE_UNDECIDED,
    VERIFICATION_POSTURE_FAMILY,
)
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now, query_one, query_rows

#: Slug prefix of the QA plans that carry a project's registered verification
#: command, one per scope. It lives here rather than beside the registration
#: that builds those slugs because registration imports this module for its
#: refusal, so the dependency only runs one way. Registration and the boot-time
#: convergence both read it from here, so a rename cannot leave the retirement
#: matching plans that are no longer created.
REGISTERED_COMMAND_PLAN_PREFIX = "registered-command-"


class VerificationPostureError(ValueError):
    """A posture write cannot be applied as asked."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _posture_payload(conn: Any, project_id: int) -> dict[str, Any]:
    marker = _p(conn)
    row = query_one(
        conn,
        "SELECT payload FROM project_structure "
        f"WHERE project_id={marker} AND family={marker} "
        "AND attachment_value='project' AND entry_key=''",
        (int(project_id), VERIFICATION_POSTURE_FAMILY),
    )
    if row is None:
        return {}
    try:
        payload = json.loads(str(row["payload"] or "{}"))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def declared_posture(conn: Any, project_id: int) -> str:
    """Return the project's stored posture, or ``undecided`` when absent."""
    posture = str(_posture_payload(conn, int(project_id)).get("posture") or "")
    return posture or POSTURE_UNDECIDED


def attests_no_tests(conn: Any, project_id: int) -> bool:
    """Whether this project has attested it has no suite to register."""
    return declared_posture(conn, int(project_id)) == POSTURE_ATTESTED_NO_TESTS


def attestation_reason(conn: Any, project_id: int) -> str:
    """The operator's recorded reason, or empty when nothing is attested."""
    return str(_posture_payload(conn, int(project_id)).get("reason") or "")


def require_no_attestation(
    conn: Any,
    *,
    project_id: int,
    project: str,
    ci_method_id: str,
) -> None:
    """Refuse a verification-command registration the attestation contradicts.

    The refusal covers every scope, not only the CI runner, because
    registering any command contradicts an attestation that there is nothing
    to run. The CI runner is named anyway: pointing a gate at a workflow the
    project just said runs no suite is the specific mis-binding this rule
    exists to make impossible.
    """
    if not attests_no_tests(conn, int(project_id)):
        return
    stored = attestation_reason(conn, int(project_id))
    raise VerificationPostureError(
        f"project {project!r} has attested it has no test suite, so no "
        f"verification command can be registered for any scope — including "
        f"the {ci_method_id!r} runner, which would point a gate at a workflow "
        f"the project just said runs nothing. Attested reason: {stored!r}. To "
        f"bind a command the project has since gained, clear the attestation "
        f"first with `yoke qa no-tests clear --project {project} --reason "
        f"<what changed>`, then re-run the registration."
    )


def _registered_command_plans(conn: Any, project_id: int) -> list[dict]:
    marker = _p(conn)
    prefix_length = len(REGISTERED_COMMAND_PLAN_PREFIX)
    return [
        dict(row)
        for row in query_rows(
            conn,
            "SELECT id, slug FROM qa_plans "
            f"WHERE project_id={marker} AND retired_at IS NULL "
            f"AND substr(slug, 1, {prefix_length})={marker} ORDER BY slug",
            (int(project_id), REGISTERED_COMMAND_PLAN_PREFIX),
        )
    ]


def _retire_registered_commands(conn: Any, project_id: int) -> list[str]:
    """Retire every registered command plan and drop its gate attachments."""
    marker = _p(conn)
    retired: list[str] = []
    for plan in _registered_command_plans(conn, int(project_id)):
        conn.execute(
            f"DELETE FROM qa_plan_project_defaults WHERE plan_id={marker}",
            (int(plan["id"]),),
        )
        conn.execute(
            f"UPDATE qa_plans SET retired_at={marker} WHERE id={marker}",
            (iso8601_now(), int(plan["id"])),
        )
        retired.append(str(plan["slug"]))
    return retired


def attest_no_tests(
    conn: Any,
    *,
    project_id: int,
    project: str,
    reason: str,
) -> dict:
    """Record the attestation and retire any registered verification command.

    Both halves commit together. Retiring inside the same write is what keeps
    the two declarations from coexisting: a project that has attested has no
    registered scope left for the boot-time command convergence to re-enter,
    so that convergence never meets a registration the attestation refuses.
    """
    from yoke_core.domain.project_structure_write import apply_patch_on_connection

    text = str(reason or "").strip()
    if not text:
        raise VerificationPostureError(
            "attesting no tests requires a reason recording why this project "
            "has no suite to bind; an attestation without a reason is an "
            "omission"
        )
    retired = _retire_registered_commands(conn, int(project_id))
    apply_patch_on_connection(
        conn,
        project,
        ops=[{
            "op": "put",
            "family": VERIFICATION_POSTURE_FAMILY,
            "attachment": "project",
            "payload": {"posture": POSTURE_ATTESTED_NO_TESTS, "reason": text},
        }],
    )
    conn.commit()
    return {
        "project": project,
        "posture": POSTURE_ATTESTED_NO_TESTS,
        "reason": text,
        "retired_plans": retired,
    }


def clear_no_tests(
    conn: Any,
    *,
    project_id: int,
    project: str,
    reason: str,
) -> dict:
    """Remove the attestation so a verification command can be registered.

    Clearing registers nothing. A project that has since gained a suite binds
    it with ``yoke qa registered-command set`` after this call, which is the
    same one command it would have run had it never attested.
    """
    from yoke_core.domain.project_structure_write import apply_patch_on_connection

    text = str(reason or "").strip()
    if not text:
        raise VerificationPostureError(
            "clearing the no-tests attestation requires a reason recording "
            "what changed"
        )
    if not attests_no_tests(conn, int(project_id)):
        stored = declared_posture(conn, int(project_id))
        raise VerificationPostureError(
            f"project {project!r} has no stored no-tests attestation to "
            f"clear; its posture is {stored!r}"
        )
    apply_patch_on_connection(
        conn,
        project,
        ops=[{
            "op": "remove",
            "family": VERIFICATION_POSTURE_FAMILY,
            "attachment": "project",
        }],
    )
    conn.commit()
    return {
        "project": project,
        "posture": POSTURE_UNDECIDED,
        "reason": text,
        "next_step": (
            "register the project's command with `yoke qa registered-command "
            f"set --project {project} --scope quick --command <argv>`"
        ),
    }


__all__ = [
    "REGISTERED_COMMAND_PLAN_PREFIX",
    "VerificationPostureError",
    "attest_no_tests",
    "attestation_reason",
    "attests_no_tests",
    "clear_no_tests",
    "declared_posture",
    "require_no_attestation",
]

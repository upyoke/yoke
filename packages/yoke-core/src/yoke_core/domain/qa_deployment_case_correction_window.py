"""When a run-bound QA case may still be corrected in place.

A deployment-run requirement is a frozen acceptance snapshot, and that is
right once it has answered: an acceptance record that can be rewritten
after the fact proves nothing. But the freeze used to start the instant the
case was materialized, which is before anyone has run it even once.

That is too early, and it is where wrong-target, missing-field and
data-precondition defects live. None of them is decidable by reading a case
-- the static checks at materialization already reject what can be read
(:func:`qa_execution_environment_target.require_case_target` rejects a case
pinned to another environment's endpoints, and the method contract rejects
malformed configuration). A probe asserting a field its endpoint does not
project, or a case asserting production data that does not exist, looks
perfectly well-formed and only reveals itself when run against the real
deployed target.

So the first run *is* the validation pass, and the window this module
defines is what makes it useful: until a case has produced a determinate
verdict, correcting it is fixing a case nobody has judged, not rewriting a
result. Once ``pass`` or ``fail`` is recorded the case has answered and the
snapshot is frozen for good -- from there the only honest correction is a
second case that supersedes it, which keeps the original verdict readable.

``undetermined`` and ``error`` deliberately do not close the window: both
mean the case did not reach a judgement, which is exactly the state a
defective case lands in.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_one


#: Verdicts that settle a case. Anything else left the question open, so it
#: leaves the correction window open too.
DETERMINATE_VERDICTS = ("pass", "fail")

CORRECTION_WINDOW_CLOSED_REASON = (
    "this deployment-run case has already recorded a determinate verdict, so "
    "its acceptance snapshot is frozen. Record a corrected case that passed "
    "in its place: yoke qa requirement supersede --requirement-id {req_id} "
    "--superseded-by-requirement-id <corrected-id> --rationale '<why>'"
)


def determinate_verdict(conn: Any, requirement_id: int) -> str:
    """The settled verdict this case has recorded, or ``""`` if none has."""
    placeholders = ",".join(["%s"] * len(DETERMINATE_VERDICTS))
    row = query_one(
        conn,
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s "
        f"AND verdict IN ({placeholders}) "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (int(requirement_id), *DETERMINATE_VERDICTS),
    )
    if row is None:
        return ""
    return str(row["verdict"] or "")


def correction_window_open(conn: Any, requirement_id: int) -> bool:
    """True while this run-bound case may still be corrected in place."""
    return not determinate_verdict(conn, int(requirement_id))


def correction_window_closed_reason(requirement_id: int) -> str:
    """Why an in-place correction was refused, and what to do instead."""
    return CORRECTION_WINDOW_CLOSED_REASON.format(req_id=int(requirement_id))


__all__ = [
    "CORRECTION_WINDOW_CLOSED_REASON",
    "DETERMINATE_VERDICTS",
    "correction_window_closed_reason",
    "correction_window_open",
    "determinate_verdict",
]

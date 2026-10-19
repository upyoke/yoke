"""Shared workflow transition used by legacy QA fixture families."""

from typing import Any

from yoke_core.domain import qa
from yoke_core.domain.qa_phase_boundary import POST_MERGE_QA_PHASES


QA_GATED_TRANSITION = "reviewed-implementation"
POST_MERGE_TRANSITION = "release"


def _transition_for_phase(qa_phase: Any, explicit: str | None) -> str:
    if explicit:
        return explicit
    phase = str(qa_phase or "verification")
    if phase in POST_MERGE_QA_PHASES:
        return POST_MERGE_TRANSITION
    return QA_GATED_TRANSITION


def add_bound_requirement(**kwargs: Any) -> int:
    """Create fixture QA attached to the phase-appropriate workflow stage."""
    explicit = kwargs.pop("workflow_transition_id", None)
    return qa.cmd_requirement_add(
        workflow_transition_id=_transition_for_phase(kwargs.get("qa_phase"), explicit),
        **kwargs,
    )


def bound_requirement_row(**kwargs: Any) -> dict[str, Any]:
    """Build one batch fixture row with its workflow transition."""
    explicit = kwargs.get("workflow_transition_id")
    return {
        **kwargs,
        "workflow_transition_id": _transition_for_phase(
            kwargs.get("qa_phase"), explicit
        ),
    }


__all__ = [
    "QA_GATED_TRANSITION",
    "POST_MERGE_TRANSITION",
    "add_bound_requirement",
    "bound_requirement_row",
]


def seed_historical_requirement(**kwargs: Any) -> int:
    """Seed pre-method rows for evidence/history tests, never through live creation."""
    from yoke_core.domain.db_helpers import connect, instant_parameter, utc_now
    from yoke_core.domain.qa_requirement_policy_validation import (
        canonical_success_policy,
    )
    from yoke_core.domain.qa_method_capabilities import encoded_capability_kinds

    db_path = kwargs.pop("db_path", None)
    kwargs["workflow_transition_id"] = _transition_for_phase(
        kwargs.get("qa_phase"), kwargs.get("workflow_transition_id")
    )
    kwargs.setdefault("blocking_mode", "blocking")
    kwargs.setdefault("requirement_source", "explicit")
    kwargs["success_policy"] = canonical_success_policy(kwargs.get("success_policy"))
    kwargs["capability_requirements"] = encoded_capability_kinds(
        kwargs.get("capability_requirements"), subject="historical fixture"
    )
    with connect(path=db_path) as conn:
        kwargs["created_at"] = instant_parameter(conn, utc_now())
        rid = conn.execute(
            f"INSERT INTO qa_requirements ({','.join(kwargs)}) VALUES ({','.join('%s' for _ in kwargs)}) RETURNING id",
            tuple(kwargs.values()),
        ).fetchone()[0]
        conn.commit()
    return int(rid)

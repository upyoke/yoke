"""Withdraw an empty post-deploy answer when an item acquires real work."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.post_deploy_verification_answer import NO_OBLIGATION_QA_KIND
from yoke_core.domain.qa_plan_attachment_retract import retract_requirements


def retract_no_obligation_for_requirement(
    conn: Any, *, item_id: int | None, requirement: Mapping[str, Any]
) -> None:
    """Retire prior declarations in the insertion transaction, retaining history.

    Run-bound snapshots never rewrite their source item, and informational
    or pre-deploy requirements do not contradict an empty post-deploy answer.
    """
    if (
        item_id is None
        or requirement.get("qa_phase") != "post_deploy"
        or str(requirement.get("blocking_mode") or "blocking") != "blocking"
        or requirement.get("qa_kind") == NO_OBLIGATION_QA_KIND
    ):
        return
    declarations = query_rows(
        conn,
        "SELECT id FROM qa_requirements WHERE item_id=%s "
        "AND deployment_run_id IS NULL AND qa_phase='post_deploy' "
        "AND qa_kind=%s AND retracted_at IS NULL ORDER BY id",
        (int(item_id), NO_OBLIGATION_QA_KIND),
    )
    retract_requirements(
        conn,
        [int(row["id"]) for row in declarations],
        reason="A blocking post-deploy requirement replaces the no-obligation declaration.",
        source="blocking_post_deploy_requirement",
    )

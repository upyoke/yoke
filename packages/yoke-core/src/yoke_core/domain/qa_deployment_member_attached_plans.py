"""The post-deploy attachment phase and the plan-to-environment match.

The owed-plan read (:mod:`deployment_qa_member_plans`) uses both.
"""

from __future__ import annotations

from typing import Any


def plan_matches_stage_environment(
    plan_environment_id: Any, stage_environment_id: int | None
) -> bool:
    """True when an unbound plan, or a plan bound to this stage's environment."""
    if plan_environment_id is None:
        return True
    return int(plan_environment_id) == int(stage_environment_id or 0)


#: The phase an item-scoped deployment QA stage credits. An attachment for
#: any other phase belongs to a workflow transition, not to a deployment.
DEPLOYMENT_ATTACHMENT_PHASE = "post_deploy"


__all__ = [
    "DEPLOYMENT_ATTACHMENT_PHASE",
    "plan_matches_stage_environment",
]

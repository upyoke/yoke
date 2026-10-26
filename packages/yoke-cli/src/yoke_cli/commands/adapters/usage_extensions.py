"""Compose usage catalogs that live in focused adapter modules."""

from __future__ import annotations

from typing import Dict

from yoke_cli.commands import qa_case
from yoke_cli.commands.adapters import claims, settings
from yoke_cli.commands.adapters import actors
from yoke_cli.commands.adapters import claims_coordination_claim
from yoke_cli.commands.adapters import claims_steering
from yoke_cli.commands.adapters import config_actor_binding
from yoke_cli.commands.adapters import project_git_bootstrap
from yoke_cli.commands.adapters import projects_level_summary
from yoke_cli.commands.adapters import steering_report
from yoke_cli.commands.adapters import qa
from yoke_cli.commands.adapters import shepherd_writes
from yoke_cli.commands.adapters import strategy_event_usage
from yoke_cli.commands.adapters import universe_levels
from yoke_cli.commands.adapters import universe_retention
from yoke_cli.commands.adapters import usage_composed_operations
from yoke_cli.commands.adapters import usage_product_surfaces
from yoke_cli.commands.adapters import workflows_item_posture
from yoke_cli.commands.adapters.usage_readiness import READINESS_USAGE_BY_ID


def extend_adapter_usage(target: Dict[str, str]) -> None:
    """Add the usage maps maintained outside the core catalog."""
    target.update(actors.USAGE_BY_FUNCTION_ID)
    target.update(READINESS_USAGE_BY_ID)
    target.update(project_git_bootstrap.USAGE_BY_FUNCTION_ID)
    target.update(projects_level_summary.USAGE_BY_FUNCTION_ID)
    target.update(qa.USAGE_BY_FUNCTION_ID)
    target.update(shepherd_writes.USAGE_BY_FUNCTION_ID)
    target.update(strategy_event_usage.USAGE_BY_FUNCTION_ID)
    target.update(usage_composed_operations.USAGE_BY_FUNCTION_ID)
    target.update(usage_product_surfaces.USAGE_BY_FUNCTION_ID)
    target.update(workflows_item_posture.USAGE_BY_FUNCTION_ID)
    target.update(claims_coordination_claim.USAGE_BY_FUNCTION_ID)
    target.update(claims_steering.USAGE_BY_FUNCTION_ID)
    target.update(config_actor_binding.USAGE_BY_FUNCTION_ID)
    target.update(steering_report.USAGE_BY_FUNCTION_ID)
    target.update(universe_levels.USAGE_BY_FUNCTION_ID)
    target.update(universe_retention.USAGE_BY_FUNCTION_ID)
    target.update(
        {
            "claims.work.release_session_scoped": claims.CLAIM_WORK_RELEASE_USAGE,
            "organizations.settings.get": settings.USAGES["get"],
            "organizations.settings.merge": settings.USAGES["set"],
            "universe.levels.get": settings.USAGES["get"],
            "universe.levels.set": settings.USAGES["set"],
            "universe.levels.reset": settings.USAGES["unset"],
            "universe.cursor_quota_order.get": settings.USAGES["get"],
            "universe.cursor_quota_order.set": settings.USAGES["set"],
            "qa.case_execution.begin": qa_case.QA_CASE_RUN_USAGE,
            "qa.plan_execution.begin": qa_case.QA_PLAN_RUN_USAGE,
            "qa.plan_execution.abort": qa_case.QA_PLAN_ABORT_USAGE,
            "qa.plan_execution.adopt": qa_case.QA_PLAN_ADOPT_USAGE,
            "qa.plan_execution.reconcile": qa_case.QA_PLAN_RECONCILE_USAGE,
            "qa.plan_review.begin": qa_case.QA_PLAN_REVIEW_BEGIN_USAGE,
            "qa.plan_review.submit": qa_case.QA_PLAN_REVIEW_SUBMIT_USAGE,
        }
    )


__all__ = ["extend_adapter_usage"]

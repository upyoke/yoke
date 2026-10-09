"""Client-readable serving floors for function ids and their arguments.

The engine registry is the write-time check: ``register()`` refuses an id
absent from the previous serving set that omits ``minimum_serving_version``.
This map is what an HTTPS client may read without importing the engine, so
a typed ``function_version_skew`` can name the floor. Keep it equal to the
floors on registered entries; the registry tests bind the two.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

#: function_id -> minimum serving version. Do not copy already-served ids here.
FUNCTION_MINIMUM_SERVING_VERSIONS: dict[str, str] = {
    "actors.role.set": "next-release",
    "actors.roster": "next-release",
    "actors.state.set": "next-release",
    "events.performance.aggregate": "next-release",
    "events.performance.detail": "next-release",
    "decision_requests.get": "next-release",
    "machine_authorization.get": "next-release",
    "machine_authorization.resolve": "next-release",
    "deployment_runs.driver.for_capture": "next-release",
    "deployment_runs.execution.attach_driver": "next-release",
    "deployment_runs.execution.bound_sources_current": "next-release",
    "deployment_runs.execution.containment_basis": "next-release",
    "deployment_runs.execution.release_driver": "next-release",
    "deployment_runs.remove_item": "next-release",
    "github.branch.head": "next-release",
    "github_actions.dispatch_tag.ensure": "next-release",
    "item_landings.list": "next-release",
    "item_landings.record": "next-release",
    "items.progress_log.get": "next-release",
    "merge_receipt.commits.attest": "next-release",
    "models.diff.run": "next-release",
    "models.level_proposal.run": "next-release",
    "models.publish.run": "next-release",
    "models.restore.run": "next-release",
    "organizations.create": "next-release",
    "models.revisions.run": "next-release",
    "packs.bundle.render": "next-release",
    "projects.environment.list": "next-release",
    "projects.level_summary.get": "next-release",
    "projects.retire": "next-release",
    "projects.unretire": "next-release",
    "qa.artifact.get": "next-release",
    "qa.artifact.rehome": "next-release",
    "qa.item_plan.retract": "next-release",
    "qa.browser_context.get": "next-release",
    "qa.case_execution.begin": "next-release",
    "qa.requirement.get": "next-release",
    "qa.requirement.list": "next-release",
    "qa.plan.get": "next-release",
    "qa.plan.list": "next-release",
    "qa.activity.list": "next-release",
    "qa.plan_execution.begin": "next-release",
    "qa.plan_execution.heartbeat": "next-release",
    "qa.plan_execution.advance": "next-release",
    "qa.plan_execution.complete": "next-release",
    "qa.plan_execution.abort": "next-release",
    "qa.plan_review.begin": "next-release",
    "qa.plan_review.submit": "next-release",
    "qa.requirement.rebind_target": "next-release",
    "strategy.coordination.append": "next-release",
    "strategy.doc.create": "next-release",
    "strategy.doc.replace": "next-release",
    "test_machine.plan_case.begin": "next-release",
    "test_machine.case.begin": "next-release",
    "test_machine.plan_case.submit": "next-release",
    "test_machine.mission.ready": "next-release",
    "test_machine.mission.access": "next-release",
    "strategy.doc.section_replace": "next-release",
    "strategy.ingest.run": "next-release",
    "strategy.revision.restore": "next-release",
    "strategy.seed_defaults.run": "next-release",
    "test_machine.bridge_diagnose": "next-release",
    "test_machine.case.abort": "next-release",
    "test_machine.case.submit": "next-release",
    "test_machine.case_execute": "next-release",
    "test_machine.desktop_access": "next-release",
    "test_machine.get": "next-release",
    "test_machine.golden_capture": "next-release",
    "test_machine.list": "next-release",
    "test_machine.operation.abort": "next-release",
    "test_machine.operation.begin": "next-release",
    "test_machine.operation.submit": "next-release",
    "test_machine.reset": "next-release",
    "test_machine.screenshot": "next-release",
    "test_machine.settings_replace": "next-release",
    "test_machine.verify": "next-release",
    "universe.level_capacity.get": "next-release",
    "universe.levels.get": "next-release",
    "universe.levels.set": "next-release",
    "workflows.canon_status.list": "next-release",
    "workflows.version.publish": "next-release",
}


@dataclass(frozen=True)
class ArgumentFloor:
    """The first serving version that accepts one argument of a served function.

    ``older_form`` names what to send a server below the floor instead, so the
    refusal can teach the form that server still accepts.
    """

    minimum_serving_version: str
    older_form: str


#: function_id -> {argument: floor}, for arguments added to an already-served
#: function. Older request models may reject unknown arguments or silently
#: ignore them. Payload refusals name this floor; adapters whose writes can be
#: ignored must also verify the success receipt echoes the requested argument.
FUNCTION_ARGUMENT_MINIMUM_SERVING_VERSIONS: dict[str, dict[str, ArgumentFloor]] = {
    "items.structured_field.section_upsert": {
        "field": ArgumentFloor(
            "next-release", "field-less --section TEXT for a top-level item section"
        ),
        "heading_level": ArgumentFloor(
            "next-release", "field-less --section TEXT for a top-level item section"
        ),
    },
    "session_control.launch.create": {
        "use_stage_level": ArgumentFloor(
            "next-release",
            "an explicit --level LEVEL or exact selection with --surface S",
        ),
        "level": ArgumentFloor(
            "next-release", "an exact selection with --surface S [--model M]"
        ),
    },
    "session_control.launch.preview": {
        "level": ArgumentFloor(
            "next-release", "an exact selection with --surface S [--model M]"
        ),
    },
}


def declared_argument_floors(
    function_id: str, payload: Mapping[str, Any] | None
) -> dict[str, ArgumentFloor]:
    """The floors of every floored argument ``payload`` actually carries."""
    floors = FUNCTION_ARGUMENT_MINIMUM_SERVING_VERSIONS.get(function_id) or {}
    present = payload or {}
    return {
        name: floor
        for name, floor in floors.items()
        if present.get(name) not in (None, "", [], {})
    }


def declared_minimum_serving_version(function_id: str) -> str:
    """Return the client-readable floor for *function_id*, or empty."""
    return str(FUNCTION_MINIMUM_SERVING_VERSIONS.get(function_id) or "").strip()


__all__ = [
    "ArgumentFloor",
    "FUNCTION_ARGUMENT_MINIMUM_SERVING_VERSIONS",
    "FUNCTION_MINIMUM_SERVING_VERSIONS",
    "declared_argument_floors",
    "declared_minimum_serving_version",
]

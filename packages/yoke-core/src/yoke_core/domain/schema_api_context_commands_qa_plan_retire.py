"""``qa`` topic wrapper-command recipe for retiring a project QA plan.

Sibling of :mod:`schema_api_context_commands_qa`, kept apart so that module
stays under the authored-file line cap.
"""

from __future__ import annotations


QA_PLAN_RETIRE_COMMANDS: list[dict] = [
    {
        "topic": "qa",
        "purpose": "Retire a project QA plan nothing depends on any more",
        "recipe": 'yoke qa plan retire PLAN --project P --reason "why"',
        "notes": (
            "Registered write qa.plan.retire, run from a session holding a "
            "live steering seat covering the plan's project. Records "
            "retired_at with the reason and actor; the plan stays readable "
            "(`yoke qa plan get`, `yoke qa plan list --include-retired`) but "
            "refuses edits and materialization. Refuses with "
            "qa_plan_retire_dependents, naming each unsettled requirement, "
            "in-flight execution and project default plus the command that "
            "settles it. Unexecuted copies on finished items retract with the "
            "retirement (retracted_requirement_ids). Repeating the call on a retired plan returns the "
            "recorded retirement unchanged."
        ),
    },
]


__all__ = ["QA_PLAN_RETIRE_COMMANDS"]

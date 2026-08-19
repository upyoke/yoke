"""Registry and convenience aliases for direct-workflow operations."""

from yoke_cli.commands.adapters.blitz import blitz_survey
from yoke_cli.commands.adapters.conflict_survey_status import (
    conflict_survey_status,
)
from yoke_cli.commands.adapters.dash import (
    dash_escalate,
    dash_evidence,
    dash_file,
    dash_survey,
)
from yoke_cli.commands.adapters.field_note_promote import field_note_promote

DIRECT_WORKFLOW_SUBCOMMAND_REGISTRY = {
    ("direct-workflow", "dash", "survey"): (
        "direct_workflow.dash.survey",
        dash_survey,
    ),
    ("direct-workflow", "blitz", "survey"): (
        "direct_workflow.blitz.survey",
        blitz_survey,
    ),
    ("direct-workflow", "dash", "evidence"): (
        "direct_workflow.dash.evidence",
        dash_evidence,
    ),
    ("direct-workflow", "dash", "escalate"): (
        "direct_workflow.dash.escalate",
        dash_escalate,
    ),
    ("direct-workflow", "conflict-survey", "status"): (
        "direct_workflow.conflict_survey.status",
        conflict_survey_status,
    ),
    ("ouroboros", "field-note", "promote"): (
        "ouroboros.field_note.promote",
        field_note_promote,
    ),
}

DIRECT_WORKFLOW_SUBCOMMAND_ALIAS_REGISTRY = {
    ("dash",): ("items.create", dash_file),
}

__all__ = [
    "DIRECT_WORKFLOW_SUBCOMMAND_ALIAS_REGISTRY",
    "DIRECT_WORKFLOW_SUBCOMMAND_REGISTRY",
]

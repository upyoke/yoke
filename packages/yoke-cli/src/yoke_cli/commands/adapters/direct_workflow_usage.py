"""Usage inventory for Dash and Blitz direct-workflow adapters."""

from yoke_cli.commands.adapters.blitz import BLITZ_SURVEY_USAGE
from yoke_cli.commands.adapters.conflict_survey_status import (
    CONFLICT_SURVEY_STATUS_USAGE,
)
from yoke_cli.commands.adapters.dash import (
    DASH_ESCALATE_USAGE,
    DASH_EVIDENCE_USAGE,
    DASH_SURVEY_USAGE,
    FIELD_NOTE_PROMOTE_USAGE,
)


USAGE_BY_FUNCTION_ID = {
    "direct_workflow.dash.survey": DASH_SURVEY_USAGE,
    "direct_workflow.blitz.survey": BLITZ_SURVEY_USAGE,
    "direct_workflow.dash.evidence": DASH_EVIDENCE_USAGE,
    "direct_workflow.dash.escalate": DASH_ESCALATE_USAGE,
    "direct_workflow.conflict_survey.status": CONFLICT_SURVEY_STATUS_USAGE,
    "ouroboros.field_note.promote": FIELD_NOTE_PROMOTE_USAGE,
}


__all__ = ["USAGE_BY_FUNCTION_ID"]

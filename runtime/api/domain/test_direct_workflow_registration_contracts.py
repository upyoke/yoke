"""Claim boundaries for direct workflow registration."""

from yoke_core.domain.handlers.direct_workflow_execution import (
    REGISTRATIONS as EXECUTION_REGISTRATIONS,
)
from yoke_core.domain.handlers.field_note_dash_promotion import (
    REGISTRATIONS as PROMOTION_REGISTRATIONS,
)


def test_registered_execution_functions_keep_claim_boundaries_explicit():
    registrations = {
        row["function_id"]: row
        for row in [*EXECUTION_REGISTRATIONS, *PROMOTION_REGISTRATIONS]
    }

    assert registrations["direct_workflow.dash.survey"]["claim_required_kind"] is None
    assert registrations["direct_workflow.blitz.survey"]["claim_required_kind"] is None
    assert (
        registrations["direct_workflow.dash.evidence"]["claim_required_kind"] == "item"
    )
    assert (
        registrations["direct_workflow.dash.escalate"]["claim_required_kind"] == "item"
    )
    assert registrations["ouroboros.field_note.promote"]["claim_required_kind"] is None

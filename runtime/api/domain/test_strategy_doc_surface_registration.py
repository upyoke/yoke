"""Registration metadata for strategy review and document execution."""

from yoke_core.domain.handlers.register_strategy_doc_surfaces import (
    REGISTRATIONS,
)


def test_leaf_registration_exposes_the_review_and_execution_contract() -> None:
    function_ids = {entry["function_id"] for entry in REGISTRATIONS}
    assert function_ids == {
        "strategy.surface.list",
        "strategy.surface.get",
        "strategy.revision.diff",
        "strategy.revision.restore",
        "strategy.parent.set",
        "strategy.coordination.append",
        "strategy.execution.get",
        "strategy.execution.link",
        "strategy.claim.acquire",
        "strategy.claim.release",
        "strategy.claim.break_glass_release",
        "strategy.doc_claim.acquire",
        "strategy.doc_claim.release",
        "strategy.doc_claim.list",
    }
    restore = next(
        entry for entry in REGISTRATIONS
        if entry["function_id"] == "strategy.revision.restore"
    )
    assert restore["side_effects"] == ["db_write", "event_emit"]
    assert restore["emitted_event_names"] == ["StrategyDocRevisionRestored"]
    override = next(
        entry for entry in REGISTRATIONS
        if entry["function_id"].endswith("break_glass_release")
    )
    assert override["claim_required_kind"] == "operator_override"
    assert override["guardrails"] == ["operator_override_required"]
    document_lock = next(
        entry for entry in REGISTRATIONS
        if entry["function_id"] == "strategy.doc_claim.acquire"
    )
    assert document_lock["target_kinds"] == ["global"]
    assert document_lock["side_effects"] == ["db_write", "event_emit"]

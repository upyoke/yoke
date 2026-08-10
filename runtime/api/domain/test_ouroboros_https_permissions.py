"""Authorization regression coverage for HTTPS Ouroboros close-out."""

from __future__ import annotations

from runtime.api.domain.test_yoke_function_permissions import _entry
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.function_authz_scope import ACTOR_SESSION, PROJECT, classify
from yoke_core.domain.ouroboros_entry_review import MAX_FIELD_NOTE_REVIEW_BATCH
from yoke_core.domain.yoke_function_permissions import (
    check_dispatch_permission,
    permission_key_for,
)


def _review_request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="ouroboros.entry.mark_reviewed",
        actor=ActorContext(actor_id="42", session_id="https-session"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_review_close_out_does_not_require_a_target_project() -> None:
    entry = _entry("ouroboros.entry.mark_reviewed")

    for payload in (
        {"entry_id": 31555},
        {
            "field_notes_before": "2026-08-01",
            "limit": MAX_FIELD_NOTE_REVIEW_BATCH,
        },
    ):
        permission = check_dispatch_permission(None, entry, _review_request(payload))
        assert permission.error is None
        assert permission.project_id is None
        assert permission.project_slug is None


def test_actor_session_override_is_limited_to_review_close_out() -> None:
    review = _entry("ouroboros.entry.mark_reviewed")
    archive = _entry("ouroboros.entry.mark_archived")

    review_spec = classify(
        review.function_id,
        side_effects=bool(review.side_effects),
        project_permission=permission_key_for(review),
    )
    archive_spec = classify(
        archive.function_id,
        side_effects=bool(archive.side_effects),
        project_permission=permission_key_for(archive),
    )

    assert review_spec.scope == ACTOR_SESSION
    assert archive_spec.scope == PROJECT

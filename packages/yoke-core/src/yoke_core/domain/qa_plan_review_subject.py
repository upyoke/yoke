"""Public subject identity and command arguments for QA review bundles."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.public_item_contract import project_public_identities
from yoke_core.domain.item_ref_render import render_item_refs


def public_review_subject(conn: Any, subject: Mapping[str, Any]) -> dict[str, Any]:
    """Render owned join keys before a review contract reaches its client."""
    refs = render_item_refs(
        conn, [subject.get("item_id"), subject.get("deployment_member_item_id")]
    )
    if subject.get("item_id") is not None and subject["item_id"] not in refs:
        raise ValueError(
            "public_response_identity_unavailable: review subject has no public ref"
        )
    return project_public_identities(dict(subject), refs.get)


def subject_flag(subject: Mapping[str, Any], target: Mapping[str, Any] | None) -> str:
    """Name the bundle subject with the canonical reviewer CLI argument."""
    if subject.get("standalone_plan_id") is not None:
        return f"--project {(target or {})['project']['slug']}"
    return (
        f"--item {subject['public_ref']}"
        if subject.get("public_ref") is not None
        else f"--deployment-run-id {subject['deployment_run_id']}"
    )

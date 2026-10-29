"""Unit tests for :mod:`yoke_core.domain.path_claim_register`.

The overlap-denial body embeds the conflicting claim
id(s), the overlapping path strings, and the
holder item and workflow-owned recovery.
"""

from __future__ import annotations


from yoke_contracts.public_ref import unresolved_item_ref
from yoke_core.domain.path_claim_register import compose_overlap_denial

# The denial composes with no connection under these tests, so there is no
# identity to read and nothing to name the item by.
UNREADABLE_INTERNAL_ID = 123


class TestComposeOverlapDenialNoConflicts:
    """When the conflict scan finds no rows (e.g. conn=None under unit
    tests), the body names the integration target and emits the
    resolution-command template with placeholders so the contract shape
    is visible. With no connection there is no identity read, so the item
    position says it could not resolve one rather than minting a ref out
    of the storage key the caller passed."""

    def test_includes_header_and_resolution_command(self) -> None:
        body = compose_overlap_denial(
            item_id=UNREADABLE_INTERNAL_ID,
            integration_target="main",
            candidate_target_ids=[],
            base_message="overlap reason text",
            conn=None,
        )
        assert "BLOCKED: path-claim register overlap" in body
        assert unresolved_item_ref(consulted=False) in body
        assert str(UNREADABLE_INTERNAL_ID) not in body
        assert "integration_target='main'" in body
        assert "overlap reason text" in body
        assert "Read the item workflow" in body
        assert "/yoke refine" not in body
        assert "coordination-decision-build" not in body

    def test_no_conflicts_uses_placeholder_claim_id(self) -> None:
        body = compose_overlap_denial(
            item_id=42,
            integration_target="main",
            candidate_target_ids=[],
            base_message="reason",
            conn=None,
        )
        # No live claim id -> placeholder shown so the operator knows
        # what to substitute.
        assert "Recovery: Read the item workflow" in body
        assert "coordination-decision-build" not in body


ITEM_PREFIX = "YOK"
OVERLAP_SEQUENCE = 17


def test_render_denial_names_claim_holder_paths_and_recovery(monkeypatch) -> None:
    """The register denial keeps conflict facts after resolving the candidate paths.

    A missing project lookup used to be swallowed, so the body named only the
    candidate item and the recovery had no claim id or shared paths.
    """
    from yoke_core.domain.path_claims import IncompatibleOverlap
    from yoke_core.domain.path_claim_register import (
        render_overlap_denial_for_register,
    )

    def conflicts(conn, integration_target, target_ids):
        if list(target_ids) != [10, 11]:
            return []
        holder = f"{ITEM_PREFIX}-{OVERLAP_SEQUENCE + 1}"
        return [(200, ["a.py", "b.py"], holder)]

    monkeypatch.setattr(
        "yoke_core.domain.path_claims_registration_context.fetch_item_project_id",
        lambda conn, item_id: 1,
    )
    monkeypatch.setattr(
        "yoke_core.domain.path_claims_resolve.resolve_paths_to_target_ids",
        lambda conn, project_id, paths, **kwargs: [10, 11],
    )
    monkeypatch.setattr(
        "yoke_core.domain.path_claim_register._resolve_conflicts",
        conflicts,
    )
    monkeypatch.setattr(
        "yoke_core.domain.path_claim_register._display_item_ref",
        lambda conn, item_id: f"{ITEM_PREFIX}-{OVERLAP_SEQUENCE}",
    )
    monkeypatch.setattr(
        "yoke_core.domain.path_claim_register._overlap_recovery",
        lambda conn, item_id, public_ref: (
            "Continue /yoke dash "
            f"{ITEM_PREFIX}-{OVERLAP_SEQUENCE}: for independent edits, "
            "read both specs and "
            "`yoke claims path coordination-decision-build --help`"
        ),
    )

    body = render_overlap_denial_for_register(
        object(),
        exc=IncompatibleOverlap(
            "path coverage overlaps an active claim on 'main'; "
            "declare an upstream dependency or wait"
        ),
        item_id=42,
        integration_target="main",
        paths=["a.py", "b.py"],
        allow_planned=False,
        session_id=None,
    )

    assert body is not None
    assert "claim 200" in body
    assert f"holder {ITEM_PREFIX}-{OVERLAP_SEQUENCE + 1}" in body
    assert "a.py" in body and "b.py" in body
    assert "coordination-decision-build" in body

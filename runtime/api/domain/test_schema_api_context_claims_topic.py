"""Claims-topic packet-content regressions.

Sibling of :mod:`test_schema_api_context`; split out so the parent module
stays under the 350-line authoring cap.

- The ``path_claims`` stanza carries the canonical JOIN through
  ``path_claim_targets`` -> ``path_targets`` and the full ``state``
  enum as a positive value listing.
- Working ``yoke claims work release`` invocations for item,
  claim-id, epic-task, and session-scoped release appear in the claims
  commands block.
- The manual spec-rewrite claim pattern (``claims work acquire
  --reason rewrite-in-progress`` -> edit ->
  ``claims work release --reason rewrite-complete``) is taught as a
  working example, not as a new skill.
"""

from __future__ import annotations

from yoke_core.domain import schema_api_context as sac


def test_claims_packet_teaches_path_claims_join_and_state_enum() -> None:
    """The packet teaches the physical path-claim join and state enum."""
    body = sac.render_topic_packet("claims")
    assert "JOIN path_claim_targets pct ON pct.claim_id = pc.id" in body
    assert "JOIN path_targets ptarget ON ptarget.id = pct.target_id" in body
    assert "there is no `path_claims.paths`" in body
    # Positive value listing — every state present, not "NOT X" prose.
    for state in ("'planned'", "'active'", "'released'", "'cancelled'", "'blocked'"):
        assert state in body, f"path_claims state enum missing value: {state}"


def test_claims_packet_teaches_release_work_claim_variants() -> None:
    """The packet teaches every registered work-claim release selector.

    The registered adapter supports one claim by item, claim id, or
    epic-task identity, plus session-scoped handoff cleanup.
    """
    body = sac.render_topic_packet("claims")
    assert "yoke claims work release --item YOK-N --reason TEXT" in body
    assert "yoke claims work release --claim-id <id> --reason TEXT" in body
    assert (
        "yoke claims work release --epic-id E --task-num K --reason TEXT"
        in body
    )
    assert "yoke claims work release --all-mine" in body


def test_claims_packet_teaches_spec_rewrite_pattern() -> None:
    """The spec rewrite pattern uses canonical ``yoke`` commands.

    Acquire → structured-field replace → release sequence, all via the
    Tier-1 grammar (current).
    """
    body = sac.render_topic_packet("claims")
    assert "yoke claims work acquire --item YOK-N --reason rewrite-in-progress" in body
    assert "yoke claims work release --item YOK-N --reason rewrite-complete" in body
    # Doctrine sentence — no new skill.
    assert "no new skill" in body.lower()

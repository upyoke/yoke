"""Claims-topic packet-content regressions.

Sibling of :mod:`test_schema_api_context`. Holds the AC-1 / AC-5 /
AC-44 / AC-50 assertions for the claims topic so the parent module
stays under the 350-line authoring cap.

- AC-1: ``path_claims`` stanza carries the canonical JOIN through
  ``path_claim_targets`` -> ``path_targets`` and the full ``state``
  enum as a positive value listing.
- AC-5: three working ``release-work-claim`` invocations
  (``--item`` / ``--epic-task`` / ``--process``) appear in the claims
  commands block.
- AC-44: the manual spec-rewrite claim pattern (``claim-work
  --reason rewrite-in-progress`` -> edit ->
  ``release-work-claim --reason rewrite-complete``) is taught as a
  working example, not as a new skill.
- AC-50: the process variant uses a key that is registered in
  :mod:`yoke_core.domain.work_processes`.
"""

from __future__ import annotations

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain import work_processes


def test_claims_packet_teaches_path_claims_join_and_state_enum() -> None:
    """AC-1."""
    body = sac.render_topic_packet("claims")
    assert "JOIN path_claim_targets pct ON pct.claim_id = pc.id" in body
    assert "JOIN path_targets ptarget ON ptarget.id = pct.target_id" in body
    assert "there is no `path_claims.paths`" in body
    # Positive value listing — every state present, not "NOT X" prose.
    for state in ("'planned'", "'active'", "'released'", "'cancelled'", "'blocked'"):
        assert state in body, f"path_claims state enum missing value: {state}"


def test_claims_packet_teaches_release_work_claim_variants() -> None:
    """AC-5 + AC-50.

    Current: the canonical ``yoke claims work release
    --item YOK-N`` form is the agent shape; the epic-task / process
    variants remain operator-debug ``release-work-claim`` fallbacks
    with no ``yoke`` CLI adapter yet.
    """
    body = sac.render_topic_packet("claims")
    assert "yoke claims work release --item YOK-N --reason TEXT" in body
    assert "release-work-claim --epic-task YOK-EPIC --task-num K --reason TEXT" in body
    assert "release-work-claim --process DOCTOR --project yoke --reason TEXT" in body
    # The process variant uses a registered key.
    assert work_processes.is_known_process("DOCTOR"), (
        "packet teaches `--process DOCTOR` but DOCTOR is not a registered "
        "process key in work_processes; pick a registered key or extend the "
        "process registry alongside this packet edit."
    )


def test_claims_packet_teaches_spec_rewrite_pattern() -> None:
    """AC-44 — canonical ``yoke <subcommand>`` agent shape.

    Acquire → structured-field replace → release sequence, all via the
    Tier-1 grammar (current).
    """
    body = sac.render_topic_packet("claims")
    assert "yoke claims work acquire --item YOK-N --reason rewrite-in-progress" in body
    assert "yoke claims work release --item YOK-N --reason rewrite-complete" in body
    # Doctrine sentence — no new skill.
    assert "no new skill" in body.lower()

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

import sqlite3

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain.schema_api_context_commands_claims import CLAIMS_COMMANDS


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
    assert "yoke claims work release --item PREFIX-N --reason TEXT" in body
    assert "yoke claims work release --claim-id <id> --reason TEXT" in body
    assert "yoke claims work release --epic-id E --task-num K --reason TEXT" in body
    assert "yoke claims work release --all-mine" in body


def test_claims_packet_teaches_spec_rewrite_pattern() -> None:
    """The spec rewrite pattern uses canonical ``yoke`` commands.

    Acquire → structured-field replace → release sequence, all via the
    Tier-1 grammar (current).
    """
    body = sac.render_topic_packet("claims")
    assert (
        "yoke claims work acquire --item PREFIX-N --reason rewrite-in-progress" in body
    )
    assert "yoke claims work release --item PREFIX-N --reason rewrite-complete" in body
    # Doctrine sentence — no new skill.
    assert "no new skill" in body.lower()


def test_claims_packet_teaches_steering_scope_claim_lifecycle() -> None:
    body = sac.render_topic_packet("claims")
    assert "kind=steering_scope" in body
    assert "[] means the whole project" in body
    assert "Intersecting live steering scopes" in body
    assert "steering claim holder" in body
    assert "owner_kind='session'" in body
    assert "registration provenance, not authority" in body
    assert (
        "yoke claims steering-scope acquire --project P [--strategy-doc SLUG]" in body
    )
    assert "yoke claims steering-scope list --project P --active-only" in body
    assert "yoke claims steering-scope release CLAIM_ID --reason TEXT" in body
    assert "stale-session reclaim free the steering scope" in body


def test_claims_packet_teaches_live_progress_log_content_flags() -> None:
    entry = next(
        command
        for command in CLAIMS_COMMANDS
        if command["purpose"].startswith("Controlled handoff")
    )
    recipe = str(entry["recipe"])
    assert '--content "<resume-context-body>"' in recipe
    assert "--content-file PATH" in recipe
    assert "--stdin" not in recipe


def test_specific_path_conflict_recipe_executes_against_canonical_columns() -> None:
    """The packet's raw diagnostic join stays executable against the schema."""
    entry = next(
        command
        for command in CLAIMS_COMMANDS
        if command["purpose"] == "Find conflicts on specific paths (SQL)"
    )
    recipe = str(entry["recipe"])
    sql = recipe.partition('yoke db read "')[2].rsplit('"', 1)[0]

    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE path_claims (
          id INTEGER PRIMARY KEY, owner_kind TEXT NOT NULL,
          owner_item_id INTEGER NOT NULL, state TEXT NOT NULL
        );
        CREATE TABLE path_targets (
          id INTEGER PRIMARY KEY, path_string TEXT NOT NULL
        );
        CREATE TABLE path_claim_targets (
          id INTEGER PRIMARY KEY,
          claim_id INTEGER NOT NULL REFERENCES path_claims(id),
          target_id INTEGER NOT NULL REFERENCES path_targets(id)
        );
        INSERT INTO path_claims (id, owner_kind, owner_item_id, state)
          VALUES (7, 'item', 42, 'active');
        INSERT INTO path_targets (id, path_string)
          VALUES (9, '<project-source-path>/foo.py');
        INSERT INTO path_claim_targets (id, claim_id, target_id)
          VALUES (11, 7, 9);
        """
    )

    assert conn.execute(sql).fetchall() == [
        (7, "item", 42, "active", "<project-source-path>/foo.py")
    ]

"""Column-disambiguation regressions for the schema cheat-sheet packet.

A recurring Yoke-surface gap: agents drop to a raw diagnostic SELECT
with a column name guessed from doctrine prose that actually belongs to a
DIFFERENT table — the prominent ``path_claims`` typed-owner vocabulary
cross-applied to ``work_claims`` is the canonical example. These tests
pin the positive disambiguation notes that steer the next agent to the
real column, per the AGENTS.md "Same-PR packet teaching on Yoke-surface
gap failures" rule. They assert against the rendered packet body, so a
future note rewrite that drops a disambiguation fails loudly.
"""

from __future__ import annotations

from yoke_core.domain import schema_api_context as sac


def test_work_claims_note_disambiguates_from_path_claims() -> None:
    """work_claims must not inherit the path_claims typed-owner columns."""
    body = sac.render_topic_packet("claims")
    # The path_claims typed-owner columns are named as NOT work_claims.
    assert "path_claims columns, NOT work_claims" in body
    assert "do not cross-apply the typed-owner vocabulary" in body
    # The real authority columns + claim timestamp are named.
    assert "session_id + target_kind + item_id/epic_id/task_num" in body
    assert "`claimed_at`" in body
    # Holder lookups steer to the registered holder command over a raw SELECT.
    assert "yoke claims work holder-get" in body


def test_harness_sessions_note_calls_out_state_and_started_at() -> None:
    """harness_sessions has neither `state` nor `started_at`."""
    body = sac.render_topic_packet("claims")
    assert "NO `state` column" in body
    assert "`started_at` column" in body
    # The real session-offer timestamp is named (and listed as a column).
    assert "`offered_at`" in body
    column_line = next(
        line for line in body.splitlines() if "**`harness_sessions`**" in line
    )
    assert "offered_at" in column_line


def test_items_note_calls_out_id_pk_and_github_issue() -> None:
    """items PK is `id` (no `item_id` column); GitHub field is `github_issue`."""
    body = sac.render_topic_packet("core")
    assert "NO `item_id` column" in body
    assert "`github_issue` column" in body
    assert "no `github_issue_number`" in body


def test_qa_requirements_note_names_qa_kind_not_kind() -> None:
    """The qa_requirements kind discriminator is `qa_kind`, not `kind`."""
    body = sac.render_topic_packet("qa")
    assert "discriminator is `qa_kind`" in body
    assert "no `requirement_type` column" in body

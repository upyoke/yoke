"""Tests for the canonical board_emoji vocabulary + celebration propagation.

Guards the global dedup: no glyph carries two meanings across the non-exempt
surfaces, the escalating-checkmark ladder, the stolen lifecycle glyphs, and the
frontier inbox-zero celebration flowing to the stats box, the Done section
header, and per-row done statuses.
"""

from __future__ import annotations

from yoke_contracts.project_contract.board_art import emoji as E
from yoke_contracts.project_contract.board_art.emoji import STATUS_EMOJI, resolve_celebration
from yoke_contracts.board.renderer_sections import render_board_sections
from yoke_contracts.board.sections_classify import ItemRow, status_emoji
from yoke_contracts.board.config import BoardConfig


class TestCanonicalVocabulary:
    def test_escalating_checkmark_ladder(self):
        # 👍 reviewed → ⛳ implemented → ✅ done, three distinct glyphs.
        ladder = [
            STATUS_EMOJI["reviewed-implementation"],
            STATUS_EMOJI["implemented"],
            STATUS_EMOJI["done"],
        ]
        assert ladder == ["👍", "⛳", "✅"]
        assert len(set(ladder)) == 3

    def test_stolen_lifecycle_glyphs(self):
        # Both refining states share 📝; plan-drafted is the drafted clipboard;
        # implementing is the hammer (freeing 🟢 for the sessions header).
        assert STATUS_EMOJI["refining-idea"] == "📝"
        assert STATUS_EMOJI["refining-plan"] == "📝"
        assert STATUS_EMOJI["plan-drafted"] == "📋"
        assert STATUS_EMOJI["implementing"] == "🔨"

    def test_freed_glyphs_no_longer_clash(self):
        vals = set(STATUS_EMOJI.values())
        # 🟢 is no longer a per-row status (now the Active Sessions header only).
        assert "🟢" not in vals
        # Bucket headers vacated the overloaded glyphs.
        assert E.ACTIVE_EMOJI == "🎫" and E.ACTIVE_EMOJI != "🔥"
        assert E.PIPELINE_EMOJI != "🚀"
        assert E.BACKLOG_EMOJI != "💡"
        # 🚀 means release only — not Pipeline, not advance.
        assert STATUS_EMOJI["release"] == "🚀"

    def test_stats_box_and_section_headers_share_buckets(self):
        # Sourced from the same constants — unification is structural.
        from yoke_contracts.board.renderer_sections import _SECTIONS

        by_key = {key: (label, emoji) for key, label, emoji in _SECTIONS}
        assert by_key["active"] == (E.ACTIVE_LABEL, E.ACTIVE_EMOJI)
        assert by_key["freezer"] == ("Frozen", E.FROZEN_EMOJI)
        assert by_key["done"] == (E.DONE_LABEL, E.DONE_EMOJI)

    def test_frozen_is_ice(self):
        assert E.FROZEN_EMOJI == "🧊"

    def test_planned_shares_refined_idea_gem(self):
        # Same "refined / ready to build" milestone at epic vs issue altitude —
        # so it shares 💎, and is now distinct from the other planning states.
        assert STATUS_EMOJI["planned"] == STATUS_EMOJI["refined-idea"] == "💎"
        assert STATUS_EMOJI["planned"] != STATUS_EMOJI["planning"]
        assert STATUS_EMOJI["planned"] != STATUS_EMOJI["plan-drafted"]


class TestCentralizedConstants:
    """Badge + velocity glyphs are sourced from board_emoji (single source)."""

    def test_badge_constants_from_registry(self):
        import yoke_contracts.board.widgets_badges as B

        assert (B._TAG, B._SHIELD, B._MAILBOX, B._MEDAL, B._TARGET, B._CLOCK) == (
            E.BADGE_TYPE, E.BADGE_ZERO_BUGS, E.BADGE_INBOX_ZERO,
            E.BADGE_MILESTONE, E.BADGE_STREAK, E.BADGE_CLOCK,
        )
        assert (
            B._AGE_FRESH, B._AGE_WEEK, B._AGE_BIWEEK, B._AGE_MONTH, B._AGE_ANCIENT
        ) == (E.AGE_FRESH, E.AGE_WEEK, E.AGE_BIWEEK, E.AGE_MONTH, E.AGE_ANCIENT)

    def test_velocity_constants_from_registry(self):
        import yoke_contracts.board.widgets_velocity_meter as V

        assert (V._FLOPPY, V._PACKAGE, V._COMPASS) == (
            E.VELOCITY_CODE, E.VELOCITY_DELIVERY, E.VELOCITY_STRATEGY,
        )


class TestResolveCelebration:
    base = {"done": 5, "active": 0, "pipeline": 0, "backlog": 0}

    def test_frontier_inbox_zero_fires(self):
        assert resolve_celebration(self.base, "frontier", 42) in E.CELEBRATION_EMOJIS

    def test_non_frontier_is_none(self):
        assert resolve_celebration(self.base, "rainbow_random", 42) is None

    def test_active_work_blocks(self):
        assert resolve_celebration(dict(self.base, active=1), "frontier", 42) is None

    def test_deterministic_given_seed(self):
        assert resolve_celebration(self.base, "frontier", 7) == resolve_celebration(
            self.base, "frontier", 7
        )


class TestStatusEmojiCelebration:
    def test_done_swapped_to_celebration(self):
        assert status_emoji("done", "🎉") == "🎉 done"

    def test_done_default_is_check(self):
        assert status_emoji("done") == f"{E.DONE_EMOJI} done"

    def test_non_done_unaffected(self):
        assert status_emoji("implementing", "🎉") == status_emoji("implementing")


class TestCelebrationPropagatesToSections:
    def test_done_header_and_row_use_celebration(self, test_db):
        done_item = ItemRow(
            1, "YOK-1", "Shipped it", "issue", "medium", "done", "—",
            None, "", "yoke", "",
        )
        buckets = {"done": [done_item]}
        lines, _ = render_board_sections(
            test_db, BoardConfig(), "yoke", buckets, {}, {}, None,
            celebration="🎉",
        )
        out = "\n".join(lines)
        assert "### 🎉 Done" in out          # header swapped
        assert "🎉 done" in out               # per-row status swapped
        assert "### ✅ Done" not in out        # normal check not used in celeb

    def test_no_celebration_uses_check(self, test_db):
        done_item = ItemRow(
            1, "YOK-1", "Shipped it", "issue", "medium", "done", "—",
            None, "", "yoke", "",
        )
        lines, _ = render_board_sections(
            test_db, BoardConfig(), "yoke", {"done": [done_item]}, {}, {}, None,
        )
        out = "\n".join(lines)
        assert "### ✅ Done" in out
        assert "✅ done" in out

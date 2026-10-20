"""Static regression coverage for the /yoke feed prompt surface."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FEED_DIR = _REPO_ROOT / ".claude" / "skills" / "yoke" / "feed"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestFeedSkillContract:
    """Feed should preserve the richer manual workflow semantics."""

    def test_skill_supports_optional_item_scope(self):
        text = _read(_FEED_DIR / "SKILL.md")
        assert "[PREFIX-N ...]" in text
        assert "`PREFIX-N` args set the focus" in text

    def test_gather_reads_strategy_and_recent_landings(self):
        text = _read(_FEED_DIR / "gather.md")
        assert "yoke strategy doc get MASTER-PLAN" in text
        assert "List which items recent landings made stale, and why." in text

    def test_decide_classifies_outcomes_and_honors_no_new_items(self):
        text = _read(_FEED_DIR / "decide.md")
        for outcome in (
            "refresh_only",
            "sharpen_frontier",
            "materialize_new",
            "leave_in_sml",
        ):
            assert f"`{outcome}`" in text
        assert "`--no-new-items` blocks creates and splits." in text

    def test_materialize_updates_existing_items_via_structured_fields(self):
        text = _read(_FEED_DIR / "materialize.md")
        assert "yoke items structured-field replace PREFIX-N" in text
        assert "Never cancel; recommend it." in text

    def test_reconcile_touches_only_feed_rows(self):
        text = _read(_FEED_DIR / "reconcile.md")
        assert "Never touch non-Feed rows." in text
        assert "Read back; record mismatches." in text

    def test_summarize_reports_exact_refs(self):
        text = " ".join(_read(_FEED_DIR / "summarize.md").split())
        assert "Report exact refs: landings, item and edge changes" in text
        assert "`--no-new-items` suppression" in text

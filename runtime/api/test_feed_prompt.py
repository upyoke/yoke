"""Static regression coverage for the /yoke feed prompt surface."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FEED_DIR = _REPO_ROOT / ".claude" / "skills" / "yoke" / "feed"
_SESSION_PATH = (
    _REPO_ROOT
    / "packages"
    / "yoke-core"
    / "src"
    / "yoke_core"
    / "domain"
    / "session.py"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestFeedSkillContract:
    """Feed should preserve the richer manual workflow semantics."""

    def test_skill_supports_optional_item_scope(self):
        text = _read(_FEED_DIR / "SKILL.md")
        assert "[YOK-N ...]" in text
        assert "_scope_ids" in text
        assert "stale-ticket refresh" in text

    def test_gather_reads_structured_fields_and_recent_landings(self):
        text = _read(_FEED_DIR / "gather.md")
        assert "items get YOK-{id} body" in text
        assert "items get YOK-{id} design_spec" in text
        assert "items get YOK-{id} technical_plan" in text
        assert "items get YOK-{id} worktree_plan" in text
        assert 'git log --oneline -30' in text
        assert 'git log --oneline --since="3 days ago"' in text
        assert "git diff <commit>~1..<commit> --stat" in text
        assert "These tickets need updating because X landed and changed Y." in text

    def test_decide_requires_recent_landing_update_assessment(self):
        text = _read(_FEED_DIR / "decide.md")
        assert "_items_to_update" in text
        assert "Did any recently landed work change a file" in text
        assert "_decision_outcomes" in text
        assert "Split/materialization work was suppressed by --no-new-tickets." in text

    def test_materialize_updates_existing_items_via_structured_fields(self):
        text = _read(_FEED_DIR / "materialize.md")
        assert 'yoke items structured-field replace YOK-{id}' in text
        assert "printf '%s\\n' \"<updated field content>\"" in text
        assert "_updated_items.append" in text
        assert "do NOT auto-cancel it inside feed" in text
        assert "Prefer the matching structured field" in text

    def test_reconcile_tracks_exact_rows_for_report(self):
        text = _read(_FEED_DIR / "reconcile.md")
        assert "_edge_mutations.append" in text
        assert "_edge_mutations" in text

    def test_summarize_reports_manual_feed_sections(self):
        text = _read(_FEED_DIR / "summarize.md")
        assert "What landed and what it changed:" in text
        assert "Tickets that need updating:" in text
        assert "Decision outcomes:" in text
        assert "Dependency rows added/updated/removed:" in text
        assert "Coding waves:" in text
        assert "Required merge order:" in text
        assert "Readiness callouts:" in text
        assert "Residual uncertainty:" in text


class TestFeedSessionDescription:
    """The shared session contract should describe feed truthfully."""

    def test_action_kind_feed_description_is_not_curation(self):
        text = _read(_SESSION_PATH)
        assert "Refresh frontier facts, update stale frontier items, and materialize new work from the SML." in text
        assert "curate, doctor" not in text

"""Shared analysis keeps exact grammar and never trusts stale file contents."""

from markdown_it import MarkdownIt

from yoke_core.domain import documentation_links as links
from yoke_core.domain import documentation_markdown as markdown
from yoke_core.domain.documentation_visuals import validate_visual_fallbacks


def test_analysis_shares_exact_text_but_expires_after_scope(monkeypatch):
    calls = []
    original = markdown._parse

    def parse(text, mode):
        calls.append((text, mode))
        return original(text, mode)

    monkeypatch.setattr(markdown, "_parse", parse)
    text = '# A *heading*\n\n[Jump](#a-heading)\n<h2 id="bad">No</h2>\n'
    with markdown.markdown_analysis_scope():
        assert links.heading_ids(text) == ["a-heading"]
        assert links.links(text)[0].target == "#a-heading"
        assert links._html_heading_ids(text) == ["bad"]
        with markdown.markdown_analysis_scope():
            assert links.heading_ids(text) == ["a-heading"]
        assert len(calls) == 1
    links.heading_ids(text)
    assert len(calls) == 2


def test_link_validation_rechecks_edited_target_in_same_scope(tmp_path):
    (tmp_path / "index.md").write_text("[target](target.md#present)\n")
    target = tmp_path / "target.md"
    target.write_text("# Present\n")
    with markdown.markdown_analysis_scope():
        assert links.validate_links(tmp_path, ["index.md"]) == []
        target.write_text("# Changed\n")
        assert [r.code for r in links.validate_links(tmp_path, ["index.md"])] == [
            "LINK_FRAGMENT_MISSING"
        ]
        target.unlink()
        assert [r.code for r in links.validate_links(tmp_path, ["index.md"])] == [
            "LINK_TARGET_MISSING"
        ]


def test_grammars_do_not_share_tokens_or_change_commonmark_results():
    text = "# Title *here*\n\n| A | B |\n| - | - |\n| x | y |\n"
    with markdown.markdown_analysis_scope():
        common = markdown.parse_markdown(text)
        expected = MarkdownIt("commonmark").parse(text)
        assert [t.as_dict() for t in common] == [t.as_dict() for t in expected]
        assert "table_open" in {
            t.type for t in markdown.parse_markdown(text, mode="visuals")
        }
        assert "table_open" not in {t.type for t in common}
        blocks = markdown.parse_markdown(text, mode="blocks")
        assert all(not t.children for t in blocks)
        assert [(t.type, t.map) for t in blocks] == [(t.type, t.map) for t in expected]


def test_visual_fast_path_keeps_fenced_markers_inert():
    assert validate_visual_fallbacks("page.md", "# Title\n\nNormal prose\n") == []
    assert (
        validate_visual_fallbacks(
            "page.md", "```html\n<!-- yoke:visual demo -->\n```\n"
        )
        == []
    )
    assert [
        r.code
        for r in validate_visual_fallbacks(
            "page.md", "# Title\n\n<!-- yoke:visual demo -->\n"
        )
    ] == ["VISUAL_FALLBACK_MISSING"]

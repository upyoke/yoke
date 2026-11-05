"""Public visuals retain their explanation in ordinary Markdown consumers."""

import pytest

from yoke_core.domain.documentation_visuals import validate_visual_fallbacks


@pytest.mark.parametrize(
    "fallback",
    [
        "Local runs on one machine.",
        "- **Local** runs on one machine.\n- Hosted connects several machines.",
        "| Mode | Reach |\n|---|---|\n| Local | One computer |",
    ],
)
@pytest.mark.parametrize("before", [True, False])
def test_prose_lists_and_tables_explain_visuals(fallback, before):
    marker = "<!-- yoke:visual hosting -->"
    parts = [fallback, marker] if before else [marker, fallback]
    assert validate_visual_fallbacks("guide.md", "# Hosting\n\n" + "\n\n".join(parts)) == []


@pytest.mark.parametrize(
    "content",
    [
        "",
        "<!-- An explanation invisible on GitHub -->",
        "```text\nExample code\n```",
        "[Read more](modes.md)",
        "![Hosting diagram](hosting.png)",
        "## A different section\n\nAn explanation elsewhere.",
    ],
)
def test_empty_or_invisible_fallback_refuses_with_repair(content):
    errors = validate_visual_fallbacks(
        "guide.md", "# Hosting\n\n<!-- yoke:visual hosting -->\n\n" + content
    )
    assert len(errors) == 1
    assert errors[0].code == "VISUAL_FALLBACK_MISSING"
    assert errors[0].target == "guide.md:3"
    assert "GitHub" in errors[0].repair


def test_fenced_example_marker_is_inert():
    assert validate_visual_fallbacks(
        "guide.md", "# Syntax\n\n```markdown\n<!-- yoke:visual hosting -->\n```"
    ) == []


def test_generated_navigation_does_not_explain_a_visual():
    errors = validate_visual_fallbacks(
        "guide.md",
        "# Hosting\n\n<!-- yoke:breadcrumbs -->\n"
        "[Guide](index.md) > Hosting\n<!-- /yoke:breadcrumbs -->\n\n"
        "<!-- yoke:visual hosting -->\n\n<!-- yoke:contents -->\n"
        "- [Local](local.md) — Choose a mode.\n<!-- /yoke:contents -->\n",
    )
    assert [r.code for r in errors] == ["VISUAL_FALLBACK_MISSING"]


def test_explanation_does_not_leak_from_previous_section():
    errors = validate_visual_fallbacks(
        "guide.md",
        "# Guide\n\nExisting prose.\n\n## Hosting\n\n<!-- yoke:visual hosting -->",
    )
    assert [r.code for r in errors] == ["VISUAL_FALLBACK_MISSING"]


def test_complete_corpus_check_enforces_fallback(tmp_path):
    from yoke_core.domain.install_bundle_docs_validation import main

    (tmp_path / "index.md").write_text("# Guide\n\n<!-- yoke:visual hosting -->\n")
    (tmp_path / "nav.yaml").write_text(
        "root:\n  title: Guide\n  summary: Start here.\n  path: index.md\n"
    )
    assert main(["check", "--root", str(tmp_path)]) == 1
    (tmp_path / "index.md").write_text(
        "# Guide\n\nLocal runs here only.\n\n<!-- yoke:visual hosting -->\n"
    )
    assert main(["check", "--root", str(tmp_path)]) == 0

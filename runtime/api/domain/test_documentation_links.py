"""Shared CommonMark fragments and containing-page link resolution."""

from dataclasses import asdict
import json
from pathlib import Path
import shutil

import pytest

from yoke_core.domain import documentation_links as links
from yoke_core.domain.documentation_navigation import route_for

FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "documentation_conformance.json").read_text())


@pytest.mark.parametrize("case", CASES["headings"])
def test_shared_heading_ids(case):
    assert links.heading_ids(case["markdown"]) == case["expected_ids"]


@pytest.mark.parametrize("case", CASES["links"])
def test_shared_resolution(case):
    result = links.resolve_link(case["page"], case["target"])
    assert asdict(result) == case["resolved"]
    assert result.target == (
        case["target"]
        if result.external
        else result.path
        + ("?" + result.query if result.query else "")
        + ("#" + result.fragment if result.fragment else "")
    )


@pytest.mark.parametrize("case", CASES["validation"])
def test_shared_validation(tmp_path, case):
    (tmp_path / "index.md").write_text(case["markdown"])
    refusals = links.validate_links(tmp_path, ["index.md"])
    assert [r.code for r in refusals] == (
        [case["expected_code"]] if case["expected_code"] else []
    )


def test_commonmark_links_include_labels_images_and_references():
    text = "[a *label*][ref] ![image `alt`](pic.png) <https://example.com>\n\n[ref]: page.md\n\n```\n[ignored](absent.md)\n```\n\n    [ignored](absent.md)\n"
    assert [(link.target, link.text) for link in links.links(text)] == [
        ("page.md", "a label"),
        ("pic.png", "image alt"),
        ("https://example.com", "https://example.com"),
    ]


@pytest.mark.parametrize(
    "target", ["../../out.md", "%2e%2e/%2e%2e/out.md", "/etc/passwd", "..\\out.md"]
)
def test_escape_refusals(target):
    with pytest.raises(ValueError, match="LINK_ESCAPES"):
        links.resolve_link("guide/setup.md", target)


def test_containing_page_fragment_routes_and_complete_fixture(tmp_path):
    shutil.copytree(FIXTURES / "documentation_corpus", tmp_path, dirs_exist_ok=True)
    pages = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.md")]
    assert links.validate_links(tmp_path, pages) == []
    resolved = links.resolve_link("guide/setup.md", "../index.md?mode=local#corpus")
    assert (
        route_for(resolved.path) + "?" + resolved.query + "#" + resolved.fragment
        == "/docs?mode=local#corpus"
    )
    encoded = links.resolve_link("guide/setup.md", "#caf%C3%A9")
    assert (
        route_for(encoded.path) + "#" + encoded.fragment
        == "/docs/guide/setup#caf%C3%A9"
    )


def test_missing_case_sensitive_fragment_and_escape(tmp_path):
    (tmp_path / "index.md").write_text(
        "# Root\n[bad](missing.md) [case](#Root) [escape](../out.md)\n"
    )
    refusals = links.validate_links(tmp_path, ["index.md"])
    assert [r.code for r in refusals] == [
        "LINK_TARGET_MISSING",
        "LINK_FRAGMENT_MISSING",
        "LINK_ESCAPES",
    ]
    assert all(r.target and r.detail and r.repair for r in refusals)


def test_html_heading_in_code_is_ignored(tmp_path):
    (tmp_path / "index.md").write_text(
        "# Root\n```html\n<h1 id='fine'>Text</h1>\n```\n\n    <h2 id='fine'>Text</h2>\n"
    )
    assert links.validate_links(tmp_path, ["index.md"]) == []


def test_cli_path_selection_and_symlink_escape(tmp_path, capsys):
    (tmp_path / "index.md").write_text("# Root\n")
    (tmp_path / "other.md").write_text("# Other\n[missing](absent.md)")
    assert links.main(["check", "--root", str(tmp_path), "--paths", "index.md"]) == 0
    assert "Links OK: 1 pages" in capsys.readouterr().out
    assert links.main(["check", "--root", str(tmp_path)]) == 1
    assert "LINK_TARGET_MISSING" in capsys.readouterr().out
    (tmp_path / "escape.md").symlink_to(tmp_path.parent / "outside.md")
    (tmp_path / "index.md").write_text("# Root\n[escape](escape.md)")
    assert links.validate_links(tmp_path, ["index.md"])[0].code == "LINK_ESCAPES"


def test_missing_root_and_unreadable_utf8_have_named_refusals(tmp_path, capsys):
    assert links.main(["check", "--root", str(tmp_path / "absent")]) == 1
    assert "LINK_TARGET_MISSING" in capsys.readouterr().out
    (tmp_path / "bad.md").write_bytes(b"\xff")
    assert links.validate_links(tmp_path, ["bad.md"])[0].code == "LINK_TARGET_MISSING"
    (tmp_path / "index.md").write_text("# Root\n[bad](bad.md#heading)")
    assert links.validate_links(tmp_path, ["index.md"])[0].code == "LINK_TARGET_MISSING"

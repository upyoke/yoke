"""Derived blocks are stable, bounded, atomic and tied to write authority."""

from pathlib import Path
import shutil

import pytest

from yoke_core.domain import documentation_render as render
from yoke_core.domain.documentation_navigation import iter_nodes, load_navigation

FIXTURE = Path(__file__).parent / "fixtures/documentation_corpus"


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    monkeypatch.setattr(
        render, "assert_target_under_session_work_authority", lambda path: None
    )
    return tmp_path


def test_consumer_fixture_is_rendered_and_idempotent(corpus, capsys):
    assert render.main(["check", "--root", str(corpus)]) == 0
    before = {p: p.read_bytes() for p in corpus.rglob("*.md")}
    assert render.main(["write", "--root", str(corpus)]) == 0
    assert render.main(["write", "--root", str(corpus)]) == 0
    assert before == {p: p.read_bytes() for p in before}
    assert "3 pages" in capsys.readouterr().out
    assert "yoke:breadcrumbs" not in (corpus / "index.md").read_text()


def test_stale_detection_repair_and_authority(corpus, capsys, monkeypatch):
    page = corpus / "guide/setup.md"
    page.write_text("# Setup\n\nAuthored teaching.\n")
    assert render.main(["check", "--root", str(corpus)]) == 1
    output = capsys.readouterr().out
    assert "STALE_NAV_BLOCK guide/setup.md" in output and "write" in output
    calls = []
    monkeypatch.setattr(
        render, "assert_target_under_session_work_authority", calls.append
    )
    assert render.main(["write", "--root", str(corpus)]) == 0
    assert calls == [page]
    assert page.read_text().startswith("# Setup\n\n<!-- yoke:breadcrumbs -->")
    assert "Authored teaching." in page.read_text()
    assert render.main(["check", "--root", str(corpus)]) == 0
    assert not list(corpus.rglob(".setup.md.*"))


def test_atomic_write_refuses_before_mutation(corpus, monkeypatch, capsys):
    page = corpus / "guide/setup.md"
    page.write_text("# Setup\n")
    before = page.read_bytes()

    def refuse(path):
        raise RuntimeError("workspace_authority: target outside held lane")

    monkeypatch.setattr(render, "assert_target_under_session_work_authority", refuse)
    assert render.main(["write", "--root", str(corpus)]) == 1
    assert page.read_bytes() == before
    assert "restore claimed write authority" in capsys.readouterr().out


def test_markers_inside_code_are_teaching(corpus):
    tree = load_navigation(corpus)
    node = tree.children[0]
    code = "```markdown\n<!-- yoke:breadcrumbs -->\n[Example](../index.md) > Example\n<!-- /yoke:breadcrumbs -->\n```"
    source = "# Guide\n\n" + code + "\n"
    result = render.render_page(tree, node, source)
    assert code in result
    assert render.render_page(tree, node, result) == result
    assert result.count("<!-- yoke:breadcrumbs -->") == 2


def test_h1_setext_and_missing_h1(corpus, capsys):
    page = corpus / "guide/setup.md"
    page.write_text("Setup\n=====\n\nTeach.\n")
    assert render.main(["write", "--root", str(corpus)]) == 0
    assert page.read_text().startswith("Setup\n=====\n\n<!-- yoke:breadcrumbs -->")
    page.write_text("No title.\n")
    assert render.main(["write", "--root", str(corpus)]) == 1
    assert "needs an H1" in capsys.readouterr().out


def test_paths_only_modify_selected_page(corpus):
    for node in iter_nodes(load_navigation(corpus)):
        (corpus / node.path).write_text(f"# {node.title}\n")
    assert (
        render.main(["write", "--root", str(corpus), "--paths", "guide/setup.md"]) == 0
    )
    assert "yoke:contents" not in (corpus / "index.md").read_text()
    assert "yoke:breadcrumbs" in (corpus / "guide/setup.md").read_text()


def test_measure_counts_wrapping_and_advisory_without_gate(corpus, capsys):
    page = corpus / "guide/setup.md"
    page.write_text("x" * 80 + "\n" * 349)
    assert (
        render.main(["measure", "--root", str(corpus), "--paths", "guide/setup.md"])
        == 0
    )
    assert "349 wrapped lines" in capsys.readouterr().out
    page.write_text(("x" * 80 + "\n") * 350)
    assert (
        render.main(["measure", "--root", str(corpus), "--paths", "guide/setup.md"])
        == 0
    )
    assert "REVIEW" in capsys.readouterr().out
    page.write_text(("x" * 80 + "\n") * 351)
    assert (
        render.main(["measure", "--root", str(corpus), "--paths", "guide/setup.md"])
        == 1
    )
    assert "LINE_LIMIT" in capsys.readouterr().out
    # An unlisted page still owes the same displayed-line limit.
    (corpus / "unlisted.md").write_text("x" * 80 * 351)
    assert render.main(["measure", "--root", str(corpus)]) == 1


def test_measure_refuses_missing_root(tmp_path, capsys):
    assert render.main(["measure", "--root", str(tmp_path / "absent")]) == 1
    assert "NAV_SCHEMA" in capsys.readouterr().out

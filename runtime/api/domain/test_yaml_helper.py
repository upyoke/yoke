from __future__ import annotations

import io
from pathlib import Path

from yoke_core.domain.yaml_helper import run_command


def _sample_file(path: Path) -> None:
    path.write_text(
        "---\n"
        "title: Example\n"
        "github_issue: #12\n"
        "updated: 2026-01-01T00:00:00Z\n"
        "---\n"
        "# Heading\n"
        "Body line\n"
    )


def test_get_and_set(tmp_path):
    target = tmp_path / "item.md"
    _sample_file(target)

    assert run_command(["set", "--no-lock", str(target), "github_issue", "#55"], out=io.StringIO(), err=io.StringIO()) == 0
    out = io.StringIO()
    assert run_command(["get", str(target), "github_issue"], out=out, err=io.StringIO()) == 0
    assert out.getvalue() == "#55\n"
    assert "updated: " in target.read_text()


def test_strip_and_first_heading(tmp_path):
    target = tmp_path / "item.md"
    _sample_file(target)

    stripped = io.StringIO()
    assert run_command(["strip", str(target)], out=stripped, err=io.StringIO()) == 0
    assert stripped.getvalue().startswith("# Heading\n")

    heading = io.StringIO()
    assert run_command(["first-heading", str(target)], out=heading, err=io.StringIO()) == 0
    assert heading.getvalue() == "Heading\n"


def test_strip_to_file_and_create(tmp_path):
    source = tmp_path / "item.md"
    _sample_file(source)
    output = tmp_path / "body.md"

    assert run_command(["strip-to-file", str(source), str(output)], out=io.StringIO(), err=io.StringIO()) == 0
    assert output.read_text().startswith("# Heading\n")

    created = tmp_path / "new.md"
    assert run_command(["create", str(created), "title=One", "priority=high"], out=io.StringIO(), err=io.StringIO()) == 0
    text = created.read_text()
    assert "title: One\n" in text
    assert "priority: high\n" in text


def test_set_without_frontmatter_fails(tmp_path):
    target = tmp_path / "plain.md"
    target.write_text("No frontmatter\n")
    err = io.StringIO()
    assert run_command(["set", "--no-lock", str(target), "title", "X"], out=io.StringIO(), err=err) == 1
    assert "no YAML frontmatter" in err.getvalue()


def test_relative_paths_resolve_from_invoke_cwd(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    target = repo / "backlog" / "001.md"
    target.parent.mkdir(parents=True)
    _sample_file(target)

    monkeypatch.setenv("YOKE_YAML_HELPER_CWD", str(repo))

    out = io.StringIO()
    assert run_command(["get", "backlog/001.md", "github_issue"], out=out, err=io.StringIO()) == 0
    assert out.getvalue() == "#12\n"

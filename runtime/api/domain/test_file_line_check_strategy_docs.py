"""Strategy-doc generated-view coverage for ``file_line_check``."""

from __future__ import annotations

import pathlib
import subprocess

from yoke_core.domain import file_line_check as flc
from yoke_core.domain.strategy_docs_header import render_file_text


def _init_repo(root: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "t@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "test"],
        check=True,
    )
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "seed"], check=True,
    )


def _lines(n: int) -> str:
    return "\n".join(f"line {i}" for i in range(n)) + "\n"


def _stage(root: pathlib.Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", rel], check=True)


def test_rendered_strategy_doc_over_limit_is_generated(tmp_path: pathlib.Path) -> None:
    _init_repo(tmp_path)
    body = _lines(500)
    text = render_file_text("OPERATIONS-NOTES", "2026-06-13T00:00:00Z", body)
    rel = ".yoke/strategy/OPERATIONS-NOTES.md"

    _stage(tmp_path, rel, text)

    assert (
        flc.classify_path(rel, repo_root=tmp_path)
        == flc.Classification.GENERATED
    )
    verdict = flc.changed_files_check(repo_root=tmp_path, staged=True)
    assert verdict.ok is True


def test_strategy_doc_without_render_header_is_enforced_as_authored(
    tmp_path: pathlib.Path,
) -> None:
    # Rendered strategy views are untracked local renders; a headerless
    # file staged under the strategy dir gets no built-in exemption and
    # is enforced like any authored markdown.
    _init_repo(tmp_path)
    rel = ".yoke/strategy/OPERATIONS-NOTES.md"

    _stage(tmp_path, rel, _lines(500))

    assert (
        flc.classify_path(rel, repo_root=tmp_path)
        == flc.Classification.AUTHORED
    )
    verdict = flc.changed_files_check(repo_root=tmp_path, staged=True)
    assert verdict.ok is False


def test_long_ordinary_new_markdown_still_fails(tmp_path: pathlib.Path) -> None:
    _init_repo(tmp_path)

    _stage(tmp_path, "notes/plan.md", _lines(500))

    verdict = flc.changed_files_check(repo_root=tmp_path, staged=True)
    assert verdict.ok is False
    assert verdict.hard_fails[0].path == "notes/plan.md"

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.product_boundary_teaching_extract import extract_recipe_rows


@pytest.mark.parametrize("language", ("bash", "sh", "shell", "text", ""))
def test_extract_recipe_rows_accepts_indented_fenced_blocks(tmp_path: Path, language):
    docs = tmp_path / "docs"
    docs.mkdir()
    docs.joinpath("recipe.md").write_text(
        "- Step:\n"
        f" ```{language}\n"
        " python3 -m yoke_core.domain.update_status YOK-1 1 failed\n"
        " ```\n",
        encoding="utf-8",
    )

    rows = list(extract_recipe_rows(tmp_path, ("docs/**/*.md",)))

    assert rows == [
        (
            "docs/recipe.md",
            3,
            "python3 -m yoke_core.domain.update_status YOK-1 1 failed",
            True,
        )
    ]


def test_text_recipe_fences_filter_noncommand_lines(tmp_path: Path):
    tmp_path.joinpath("recipe.md").write_text(
        "```text\nRead the receipt first.\nyoke merge audit PREFIX-N\n```\n"
    )
    assert list(extract_recipe_rows(tmp_path, ("*.md",))) == [
        ("recipe.md", 3, "yoke merge audit PREFIX-N", True)
    ]

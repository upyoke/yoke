from __future__ import annotations

from pathlib import Path

from yoke_cli.product_boundary_teaching_extract import extract_recipe_rows


def test_extract_recipe_rows_accepts_indented_fenced_blocks(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    docs.joinpath("recipe.md").write_text(
        "- Step:\n"
        " ```bash\n"
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

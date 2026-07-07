"""Regression: the board-art emoji-block registry is project-policy exempt.

The ``MIXED_EMOJI_COLUMNS`` registry is a large static data table (one entry per
art block), not authored logic. YOK-1902 relocated it to yoke_contracts package
data (``board_art/data/mixed_emoji_columns.txt``); Yoke's repo-local
``.yoke/file-line-exceptions`` exempts it without making every managed
project inherit the same package path.
"""
from __future__ import annotations

import pathlib

from yoke_core.domain import file_line_check as flc


def test_art_data_registry_is_temporary_exception(tmp_path: pathlib.Path) -> None:
    policy = tmp_path / ".yoke" / "file-line-exceptions"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        "packages/yoke-contracts/src/yoke_contracts/project_contract"
        "/board_art/data/mixed_emoji_columns.txt\n",
        encoding="utf-8",
    )
    assert (
        flc.classify_path(
            "packages/yoke-contracts/src/yoke_contracts/project_contract"
            "/board_art/data/mixed_emoji_columns.txt",
            repo_root=tmp_path,
        )
        == flc.Classification.TEMPORARY_EXCEPTION
    )

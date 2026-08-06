"""Repository contracts for DB-owned board appearance and scope."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CURRENT_TEACHING = (
    ".yoke/README.md",
    ".yoke/board-art",
    "README.md",
    "docs/local-setup-reference.md",
    "docs/OVERVIEW.md",
    "runtime/api/board/README.md",
    "packages/yoke-cli/src/yoke_cli/commands/adapters/render.py",
)


def test_checkout_does_not_track_retired_board_settings_file() -> None:
    assert not (REPO_ROOT / ".yoke" / "board.json").exists()


def test_current_teaching_does_not_name_retired_board_settings_file() -> None:
    for relative in CURRENT_TEACHING:
        body = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "board.json" not in body, relative


def test_current_teaching_names_db_board_policy() -> None:
    for relative in (
        ".yoke/README.md",
        ".yoke/board-art",
        "README.md",
        "docs/OVERVIEW.md",
    ):
        body = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "project-policy.settings.board" in body, relative

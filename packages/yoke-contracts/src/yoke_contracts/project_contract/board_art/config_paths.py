"""Path helpers for project-local board config and art files."""

from __future__ import annotations

from pathlib import Path


BOARD_CONFIG_FILENAME = "board.json"
BOARD_ART_FILENAME = "board-art"


def board_config_path(repo_root: str | Path) -> Path:
    return Path(repo_root).expanduser() / ".yoke" / BOARD_CONFIG_FILENAME


def board_art_path_for_config(config_path: str | None, repo_root: str | None = None) -> Path:
    """Return the board-art file for a config path or project checkout."""
    if repo_root:
        return Path(repo_root).expanduser() / ".yoke" / BOARD_ART_FILENAME
    if config_path is None:
        return Path.cwd() / ".yoke" / BOARD_ART_FILENAME
    path = Path(config_path)
    if path.name != "config":
        return path
    art_path = path.with_name(BOARD_ART_FILENAME)
    if art_path.is_file():
        return art_path
    return path

"""DB-owned board settings under ``project-policy.settings.board``.

Hard-cut home for every former ``BoardConfig`` / ``.yoke/board.json`` knob
plus former machine ``projects[].board.scope``. Render path is the fixed
checkout-relative convention ``.yoke/BOARD.md`` (not a settings key).
"""

from __future__ import annotations

from dataclasses import fields, MISSING, asdict
from typing import Any, Mapping

from yoke_contracts.board.config import BoardConfig, config_from_values

# Closed scope vocabulary: ``all`` covers every visible project; any other
# non-empty string is a project id or slug filter (same forms the board
# rebuild scope resolver already accepts).
DEFAULT_BOARD_SCOPE = "all"
BOARD_SCOPE_KEY = "scope"


def board_settings_defaults() -> dict[str, Any]:
    """Return the nested ``board`` object seeded into project-policy."""

    knobs = {
        field.name: field.default
        for field in fields(BoardConfig)
        if field.default is not MISSING
    }
    # Factory-default catch-all is not a knob; omit it from the seed.
    payload = dict(knobs)
    payload[BOARD_SCOPE_KEY] = DEFAULT_BOARD_SCOPE
    return payload


def board_config_from_settings(board: Mapping[str, Any] | None) -> BoardConfig:
    """Build a :class:`BoardConfig` from a ``project-policy.settings.board`` object."""

    if not isinstance(board, Mapping):
        return BoardConfig()
    values = {k: v for k, v in board.items() if k != BOARD_SCOPE_KEY}
    return config_from_values(values)


def board_scope_from_settings(
    board: Mapping[str, Any] | None,
    *,
    project_id: int | None = None,
) -> str:
    """Resolve board scope from DB settings, falling back to project id or all."""

    if isinstance(board, Mapping):
        raw = board.get(BOARD_SCOPE_KEY)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    if project_id is not None:
        return str(int(project_id))
    return DEFAULT_BOARD_SCOPE


def board_settings_from_config(
    config: BoardConfig,
    *,
    scope: str = DEFAULT_BOARD_SCOPE,
) -> dict[str, Any]:
    """Serialize a live config plus scope into the DB board object shape."""

    payload = asdict(config)
    payload.pop("rainbow_sub_weights", None)
    payload[BOARD_SCOPE_KEY] = (
        scope.strip() if isinstance(scope, str) and scope.strip()
        else DEFAULT_BOARD_SCOPE
    )
    return payload


def merge_board_file_values(
    base: Mapping[str, Any] | None,
    file_values: Mapping[str, Any] | None,
    *,
    scope: str | None = None,
) -> dict[str, Any]:
    """Overlay a former board.json (and optional machine scope) onto defaults."""

    merged = dict(board_settings_defaults())
    if isinstance(base, Mapping):
        merged.update({k: v for k, v in base.items() if v is not None})
    if isinstance(file_values, Mapping):
        for key, value in file_values.items():
            if key == "rainbow_sub_weights":
                continue
            if key.startswith("art_override__"):
                continue
            merged[key] = value
    if isinstance(scope, str) and scope.strip():
        merged[BOARD_SCOPE_KEY] = scope.strip()
    return merged


__all__ = [
    "BOARD_SCOPE_KEY",
    "DEFAULT_BOARD_SCOPE",
    "board_config_from_settings",
    "board_scope_from_settings",
    "board_settings_defaults",
    "board_settings_from_config",
    "merge_board_file_values",
]

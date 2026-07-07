"""Live in-process board render — the server-side composition.

``render_board`` opens a :class:`yoke_core.board.db.BoardDB`, collects the
query plan from the connected DB, then renders from the recorded payload — the
same data-fed assembly an https-fetched payload feeds. The render-from-payload
path and the shared ``_assemble`` are client-tier and live in the shipped
:mod:`yoke_contracts.board.renderer`; they are re-exported here for existing
importers.

Public API
----------
- ``render_board(db_token, scope, config_path, seed, repo_root) -> str``
  — collect + replay against the connected DB in one process (tests,
  direct in-process callers).
- ``render_board_from_payload(payload, ...) -> str`` — render from a
  fetched ``board.data.get`` payload with no DB connection (the
  ``yoke board rebuild`` composition, both transports). Re-exported
  from ``yoke_contracts.board.renderer``.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.board.art import parse_art_config
from yoke_contracts.board.config import parse_config
from yoke_core.board.db import BoardDB
from yoke_contracts.board.phase_timer import PhaseRecorder, measure_phase
from yoke_contracts.board.zen import _zen_extract_vision

# Render-from-payload + the shared assembly are client-tier (no DB connection);
# they ship in yoke_contracts.board.renderer and are re-exported here.
from yoke_contracts.board.renderer import (  # noqa: F401
    _assemble,
    _count_expected_tasks,
    _project_filter,
    render_board_from_payload,
)


def render_board(
    db_token: Optional[str],
    scope: str,
    config_path: str | None,
    seed: Optional[int] = None,
    repo_root: Optional[str] = None,
    phase_recorder: PhaseRecorder | None = None,
) -> str:
    """Render the complete BOARD.md content against the connected DB.

    The in-process composition of the board data layer: collect the
    query plan from the live DB, then render from the recorded payload
    — the same data-fed assembly an https-fetched payload feeds.

    Parameters
    ----------
    db_token:
        Legacy fixture token accepted for older call sites. Authority is
        resolved from the configured Postgres DSN.
    scope:
        Project scope (e.g. ``"yoke"``, ``"all"``).
    config_path:
        Optional explicit JSON or key=value settings path for tests/operator-debug.
        Normal runtime reads board settings from ``<repo_root>/.yoke/board.json``
        and art from ``<repo_root>/.yoke/board-art``.
    seed:
        Explicit random seed for deterministic art/variant selection.
        When ``None``, the production default (non-deterministic) is used.
    repo_root:
        Repository root path, used by the zen vision labels, velocity
        meter, and commit-derived widgets for file-system lookups.
        ``None`` disables those features.

    Returns
    -------
    str
        Complete board markdown content.
    """
    from yoke_core.board.data import collect_board_data

    config = parse_config(config_path, repo_root=repo_root)
    art_config = parse_art_config(config_path, repo_root=repo_root)
    vision_entries = _zen_extract_vision(repo_root) if repo_root else []

    with measure_phase(phase_recorder, "db_connect"):
        db = BoardDB(db_token)
    with db:
        with measure_phase(phase_recorder, "collect_board_data"):
            payload = collect_board_data(
                db,
                scope=scope,
                config=config,
                repo_root=repo_root,
                vision_entries=vision_entries,
            )
    return render_board_from_payload(
        payload,
        scope=scope,
        config=config,
        art_config=art_config,
        seed=seed,
        repo_root=repo_root,
        vision_entries=vision_entries,
        phase_recorder=phase_recorder,
    )

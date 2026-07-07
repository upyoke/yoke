"""Render the board text used by ``yoke board rebuild``.

This module owns the transport-safe composition shared by write mode and
terminal-print modes: fetch the recorded board data via ``board.data.get``,
render markdown locally, then merge it with any existing BOARD.md wrapper.
"""

from __future__ import annotations

import dataclasses
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from yoke_contracts.board.phase_timer import PhaseRecorder, measure_phase
from yoke_core.domain.rebuild_board_splice import _fresh_board_text, splice_board


class BoardDataFetchError(RuntimeError):
    """``board.data.get`` returned a failure envelope."""


def timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S %Z")


def parse_seed() -> int | None:
    raw = os.environ.get("BOARD_SEED", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def fetch_board_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch the recorded board data payload over the active transport."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        build_actor,
        call_dispatcher,
    )

    response = call_dispatcher(
        function_id="board.data.get",
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(),
    )
    if not response.success:
        error = response.error
        detail = (
            f"{error.code}: {error.message}" if error is not None
            else "unknown error"
        )
        raise BoardDataFetchError(f"board.data.get failed - {detail}")
    return dict(response.result or {})


def fetch_and_render(
    repo_root: Path,
    scope: str,
    phase_recorder: PhaseRecorder | None,
) -> str:
    """Fetch the board data payload and render markdown locally."""
    from yoke_contracts.board.art import parse_art_config
    from yoke_contracts.board.config import parse_config
    from yoke_core.board.renderer import render_board_from_payload
    from yoke_contracts.board.zen import _zen_extract_vision

    root_token = str(repo_root)
    config = parse_config(None, repo_root=root_token)
    art_config = parse_art_config(None, repo_root=root_token)
    vision_entries = _zen_extract_vision(root_token)
    with measure_phase(phase_recorder, "fetch_board_data"):
        payload = fetch_board_data({
            "scope": scope,
            "config_values": dataclasses.asdict(config),
            "zen_vision_count": len(vision_entries),
            "repo_root_token": root_token,
        })
    with measure_phase(phase_recorder, "render_total"):
        return render_board_from_payload(
            payload,
            scope=scope,
            config=config,
            art_config=art_config,
            seed=parse_seed(),
            repo_root=root_token,
            vision_entries=vision_entries,
            phase_recorder=phase_recorder,
        )


def build_board_file_text(
    *,
    repo_root: Path,
    board_path: Path,
    scope: str,
    phase_recorder: PhaseRecorder | None,
) -> str:
    """Return the exact BOARD.md text that write mode would persist."""
    board_content = fetch_and_render(repo_root, scope, phase_recorder)
    with measure_phase(phase_recorder, "merge_existing_board"):
        if not board_path.is_file():
            return _fresh_board_text(board_content, timestamp())
        return splice_board(
            board_path.read_text(encoding="utf-8"),
            board_content,
            timestamp(),
        )


__all__ = [
    "BoardDataFetchError",
    "build_board_file_text",
    "fetch_and_render",
    "fetch_board_data",
    "parse_seed",
    "timestamp",
]

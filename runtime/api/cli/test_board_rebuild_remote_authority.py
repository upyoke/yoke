"""Board rebuild stays local when the active control plane is remote."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from yoke_cli.board import outcome as rebuild_outcome
from yoke_cli.main import main as cli_main
from yoke_contracts.control_plane_locality import remote_control_plane
from yoke_contracts.timestamps import parse_instant


def test_board_rebuild_skips_db_telemetry_for_remote_authority(
    tmp_path: Path,
) -> None:
    board_path = tmp_path / ".yoke" / "BOARD.md"

    clock = parse_instant("1970-01-01T05:29:59.123456+05:30")
    stdout = io.StringIO()
    with (
        patch(
            "yoke_cli.commands.adapters.board._NullTiming.utc_now", return_value=clock
        ),
        remote_control_plane(),
        patch(
            "yoke_cli.board.rebuild.resolve_main_repo_root",
            return_value=tmp_path,
        ),
        patch(
            "yoke_cli.board.rebuild.rebuild",
            return_value=rebuild_outcome.rebuilt(board_path),
        ) as rebuild,
        patch(
            "yoke_core.domain.events_writes.hook_emit_connection",
            side_effect=AssertionError("remote rebuild must not open DB telemetry"),
        ),
    ):
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            result = cli_main(["board", "rebuild", "--json"])

    assert result == 0
    rebuild.assert_called_once()

    payload = json.loads(stdout.getvalue())["result"]
    assert (
        payload["started_at"]
        == payload["completed_at"]
        == "1969-12-31T23:59:59.123456Z"
    )

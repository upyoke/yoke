"""Installable-CLI contracts for DB-owned board settings."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from yoke_cli.board import rebuild as board_rebuild
from yoke_cli.board import outcome as board_outcome
from yoke_cli.config import machine_config
from yoke_cli.main import main as cli_main


def test_cli_machine_config_ignores_retired_board_entry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({
            "projects": {
                str(checkout): {
                    "project_id": 7,
                    "board": {
                        "scope": "all",
                        "render_path": ".yoke/BOARD-ALL.md",
                    },
                },
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(config))

    assert machine_config.board_scope(checkout) == "7"
    assert machine_config.board_render_path(checkout) == (
        checkout / ".yoke" / "BOARD.md"
    )


def test_rebuild_ignores_retired_board_json_when_payload_settings_are_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from yoke_cli.board import code_days_publish
    checkout = tmp_path / "checkout"
    retired_file = checkout / ".yoke" / "board.json"
    retired_file.parent.mkdir(parents=True)
    retired_file.write_text(
        json.dumps({"dashboard_weather": False}),
        encoding="utf-8",
    )
    captured = {}

    monkeypatch.setattr(board_rebuild, "parse_art_config", lambda *_a, **_k: object())
    monkeypatch.setattr(board_rebuild, "_zen_extract_vision", lambda *_a, **_k: [])
    monkeypatch.setattr(board_rebuild.machine_config, "project_id", lambda *_a: 7)
    monkeypatch.setattr(code_days_publish, "code_days_for_checkout", lambda *_a, **_k: [])
    monkeypatch.setattr(
        board_rebuild,
        "fetch_board_data",
        lambda _payload: {"config_values": {}, "scope": "7"},
    )

    def fake_render(_payload, *, config, **_kwargs):
        captured["config"] = config
        return "rendered"

    monkeypatch.setattr(board_rebuild, "render_board_from_payload", fake_render)

    assert board_rebuild.fetch_and_render(checkout, "", None) == "rendered"
    assert captured["config"].dashboard_weather is True


def test_board_adapter_defers_omitted_scope_to_project_policy(
    tmp_path: Path,
) -> None:
    board_path = tmp_path / ".yoke" / "BOARD.md"
    stdout = io.StringIO()
    stderr = io.StringIO()

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}), patch(
        "yoke_cli.board.rebuild.resolve_main_repo_root",
        return_value=tmp_path,
    ), patch(
        "yoke_cli.board.rebuild.rebuild",
        return_value=board_outcome.rebuilt(board_path),
    ) as rebuild, patch(
        "yoke_core.cli.board_rebuild_timing_events.emit_event",
    ), redirect_stdout(stdout), redirect_stderr(stderr):
        rc = cli_main(["board", "rebuild"])

    assert rc == 0
    assert rebuild.call_args.kwargs["scope"] == ""

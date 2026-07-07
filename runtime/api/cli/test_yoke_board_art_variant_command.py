"""Tests for ``yoke board art variant create``."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from yoke_contracts.project_contract.board_art.config import parse_art_config
from yoke_cli.commands.board_art.variant import (
    board_art_variant_create,
)
from yoke_cli.main import main as cli_main
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_contracts.project_contract import board_art as art_seed
from yoke_contracts.project_contract.board_art import (
    DEFAULT_VARIANT_MAX_WIDTH,
    render_board_art,
)


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "buzz"
    yoke_dir = repo / ".yoke"
    yoke_dir.mkdir(parents=True)
    (yoke_dir / "board-art").write_text(
        render_board_art("Buzz"),
        encoding="utf-8",
    )
    return repo


def test_board_art_variant_create_token_resolves() -> None:
    resolved = resolve_tool_shaped([
        "board", "art", "variant", "create", "--mixed",
    ])
    assert resolved is not None
    adapter, rest = resolved
    assert adapter is board_art_variant_create
    assert rest == ["--mixed"]


def test_ascii_apply_appends_width_bounded_variant(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    board_art = repo / ".yoke" / "board-art"
    before = board_art.read_text(encoding="utf-8")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_main([
            "board", "art", "variant", "create",
            "--ascii",
            str(repo),
            "--display-name", "Buzz",
            "--seed", "cli-seed",
            "--apply",
        ])

    assert rc == 0
    after = board_art.read_text(encoding="utf-8")
    assert after != before
    assert after.count("## ASCII") == before.count("## ASCII") + 1
    assert "Applied ASCII variant" in out.getvalue()

    cfg = parse_art_config(str(board_art))
    added = cfg.ascii_variants[-1]
    assert max(art_seed._visual_width(line) for line in added.lines) <= (
        DEFAULT_VARIANT_MAX_WIDTH
    )


def test_mixed_json_preview_does_not_apply_without_apply_flag(
    tmp_path: Path,
) -> None:
    repo = _seed_repo(tmp_path)
    board_art = repo / ".yoke" / "board-art"
    before = board_art.read_text(encoding="utf-8")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_main([
            "board", "art", "variant", "create",
            "--mixed",
            str(repo),
            "--display-name", "Buzz",
            "--seed", "cli-seed",
            "--json",
        ])

    assert rc == 0
    assert board_art.read_text(encoding="utf-8") == before
    payload = json.loads(out.getvalue())
    assert payload["kind"] == "Mixed"
    assert payload["applied"] is False
    assert art_seed._art_visual_width(payload["text"]) <= (
        DEFAULT_VARIANT_MAX_WIDTH
    )


def test_board_art_variant_inventory_marks_command_tool_shaped() -> None:
    from yoke_cli import operation_inventory as inv

    entry = inv.lookup("yoke board art variant create")
    assert entry is not None
    assert entry.status == inv.PERMANENT
    assert entry.reason == inv.REASON_TOOL_SHAPED

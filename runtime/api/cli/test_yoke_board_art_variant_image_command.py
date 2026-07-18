"""Image-backed tests for ``yoke board art variant create``."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from yoke_contracts.project_contract.board_art.config import parse_art_config
from yoke_cli.main import main as cli_main
from yoke_contracts.project_contract import board_art as art_seed
from yoke_contracts.project_contract.board_art import (
    DEFAULT_VARIANT_MAX_WIDTH,
    render_board_art,
)
from yoke_contracts.project_contract.board_art.image_to_emoji import (
    IMAGE_BLOCK_MAX_ASPECT_RATIO,
    IMAGE_BLOCK_MAX_HEIGHT,
    IMAGE_BLOCK_MAX_WIDTH,
    IMAGE_BLOCK_MIN_ASPECT_RATIO,
)


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "externalwebapp"
    yoke_dir = repo / ".yoke"
    yoke_dir.mkdir(parents=True)
    (yoke_dir / "board-art").write_text(
        render_board_art("ExternalWebapp"),
        encoding="utf-8",
    )
    return repo


def _write_image(path: Path) -> None:
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (8, 4), (245, 245, 245))
    pixels = image.load()
    for x in range(4):
        for y in range(4):
            pixels[x, y] = (220, 40, 40)
    for x in range(4, 8):
        for y in range(4):
            pixels[x, y] = (40, 100, 220)
    image.save(path, format="PNG")


def test_image_json_preview_generates_mixed_variant_without_applying(
    tmp_path: Path,
) -> None:
    pytest.importorskip("PIL")
    repo = _seed_repo(tmp_path)
    image_path = tmp_path / "logo.png"
    _write_image(image_path)
    board_art = repo / ".yoke" / "board-art"
    before = board_art.read_text(encoding="utf-8")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_main([
            "board", "art", "variant", "create",
            "--image", str(image_path),
            str(repo),
            "--display-name", "ExternalWebapp",
            "--seed", "image-seed",
            "--image-max-area-ratio", "0.4",
            "--image-max-width", "16",
            "--image-max-height", "10",
            "--image-min-aspect", "1",
            "--image-max-aspect", "2",
            "--json",
        ])

    assert rc == 0
    assert board_art.read_text(encoding="utf-8") == before
    payload = json.loads(out.getvalue())
    assert payload["kind"] == "Mixed"
    assert payload["emoji_source"] == "image"
    assert payload["applied"] is False
    assert payload["image"]["source_format"] == "PNG"
    assert payload["image"]["crop_left"] == 0
    assert payload["image"]["crop_top"] == 0
    assert payload["image"]["crop_right"] == payload["image"]["source_width"]
    assert payload["image"]["crop_bottom"] == payload["image"]["source_height"]
    assert payload["image"]["emoji_cells"] <= payload["image"]["emoji_max_cells"]
    assert payload["image"]["emoji_width"] <= 16
    assert payload["image"]["emoji_height"] <= 10
    assert 1 <= (
        payload["image"]["emoji_width"] / payload["image"]["emoji_height"]
    ) <= 2
    assert art_seed._art_visual_width(payload["text"]) <= (
        DEFAULT_VARIANT_MAX_WIDTH
    )
    assert any(emoji in payload["text"] for emoji in ("🟥", "🔴", "🍎"))
    assert any(emoji in payload["text"] for emoji in ("🟦", "🔵", "💙"))


def test_image_apply_appends_mixed_variant(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    repo = _seed_repo(tmp_path)
    image_path = tmp_path / "logo.png"
    _write_image(image_path)
    board_art = repo / ".yoke" / "board-art"
    before = board_art.read_text(encoding="utf-8")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_main([
            "board", "art", "variant", "create",
            "--image", str(image_path),
            str(repo),
            "--display-name", "ExternalWebapp",
            "--seed", "image-seed",
            "--apply",
        ])

    assert rc == 0
    after = board_art.read_text(encoding="utf-8")
    assert after != before
    assert after.count("## Mixed") == before.count("## Mixed") + 1
    assert "Applied Mixed variant" in out.getvalue()

    cfg = parse_art_config(str(board_art))
    added = cfg.mixed_variants[-1]
    assert len(added.lines) >= 4
    assert len(added.lines) <= IMAGE_BLOCK_MAX_HEIGHT
    assert max(art_seed._visual_width(line) for line in added.lines) <= (
        DEFAULT_VARIANT_MAX_WIDTH
    )
    assert any("🔴" in line or "🟥" in line or "🍎" in line for line in added.lines)
    assert any("🔵" in line or "🟦" in line or "💙" in line for line in added.lines)


def test_image_json_preview_defaults_to_twenty_cell_image_box(
    tmp_path: Path,
) -> None:
    pytest.importorskip("PIL")
    repo = _seed_repo(tmp_path)
    (repo / ".yoke" / "board-art").write_text(
        render_board_art("Yoke"),
        encoding="utf-8",
    )
    image_path = tmp_path / "square-logo.png"
    Image = pytest.importorskip("PIL.Image")
    Image.new("RGB", (40, 40), (220, 40, 40)).save(image_path, format="PNG")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_main([
            "board", "art", "variant", "create",
            "--image", str(image_path),
            str(repo),
            "--display-name", "Yoke",
            "--seed", "image-square-seed",
            "--json",
        ])

    assert rc == 0
    payload = json.loads(out.getvalue())
    assert payload["image"]["emoji_width"] == IMAGE_BLOCK_MAX_WIDTH
    assert payload["image"]["emoji_height"] == IMAGE_BLOCK_MAX_HEIGHT


def test_image_json_preview_uses_image_only_when_translated_image_is_wide(
    tmp_path: Path,
) -> None:
    Image = pytest.importorskip("PIL.Image")
    repo = _seed_repo(tmp_path)
    image_path = tmp_path / "wide-logo.png"
    Image.new("RGB", (100, 10), (255, 255, 255)).save(image_path, format="PNG")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_main([
            "board", "art", "variant", "create",
            "--image", str(image_path),
            str(repo),
            "--display-name", "Hatch",
            "--seed", "image-only-seed",
            "--json",
        ])

    assert rc == 0
    payload = json.loads(out.getvalue())
    assert payload["kind"] == "Emoji"
    assert payload["text"] == payload["image"]["emoji_text"]
    assert payload["image"]["emoji_width"] == DEFAULT_VARIANT_MAX_WIDTH // 2
    assert payload["image"]["emoji_height"] == IMAGE_BLOCK_MAX_HEIGHT
    assert payload["image"]["crop_left"] == 0
    assert payload["image"]["crop_right"] == payload["image"]["source_width"]
    assert art_seed._art_visual_width(payload["text"]) == DEFAULT_VARIANT_MAX_WIDTH


def test_image_apply_appends_image_only_variant_when_image_is_wide(
    tmp_path: Path,
) -> None:
    Image = pytest.importorskip("PIL.Image")
    repo = _seed_repo(tmp_path)
    image_path = tmp_path / "wide-logo.png"
    Image.new("RGB", (100, 10), (255, 255, 255)).save(image_path, format="PNG")
    board_art = repo / ".yoke" / "board-art"
    before = board_art.read_text(encoding="utf-8")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_main([
            "board", "art", "variant", "create",
            "--image", str(image_path),
            str(repo),
            "--display-name", "Hatch",
            "--seed", "image-only-seed",
            "--apply",
        ])

    assert rc == 0
    after = board_art.read_text(encoding="utf-8")
    assert after != before
    assert after.count("## Emoji") == before.count("## Emoji") + 1
    assert after.count("## Mixed") == before.count("## Mixed")
    assert "Applied Emoji variant" in out.getvalue()

    cfg = parse_art_config(str(board_art))
    added = cfg.emoji_variants[-1]
    assert max(art_seed._visual_width(line) for line in added.lines) == (
        DEFAULT_VARIANT_MAX_WIDTH
    )


def test_image_json_preview_squishes_wide_logo_to_full_height(
    tmp_path: Path,
) -> None:
    Image = pytest.importorskip("PIL.Image")
    repo = _seed_repo(tmp_path)
    image_path = tmp_path / "wide-logo.png"
    image = Image.new("RGB", (100, 10), (255, 255, 255))
    pixels = image.load()
    for x in range(0, 20):
        for y in range(10):
            pixels[x, y] = (220, 40, 40)
    for x in range(80, 100):
        for y in range(2, 8):
            pixels[x, y] = (20, 20, 20)
    image.save(image_path, format="PNG")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_main([
            "board", "art", "variant", "create",
            "--image", str(image_path),
            str(repo),
            "--display-name", "Hatch",
            "--seed", "image-wide-seed",
            "--max-width", "300",
            "--json",
        ])

    assert rc == 0
    payload = json.loads(out.getvalue())
    assert payload["kind"] == "Emoji"
    assert payload["image"]["emoji_width"] == round(
        IMAGE_BLOCK_MAX_HEIGHT * IMAGE_BLOCK_MAX_ASPECT_RATIO
    )
    assert payload["image"]["emoji_height"] == IMAGE_BLOCK_MAX_HEIGHT
    assert payload["image"]["crop_left"] == 0
    assert payload["image"]["crop_right"] == payload["image"]["source_width"]
    assert payload["image"]["crop_top"] == 0
    assert payload["image"]["crop_bottom"] == payload["image"]["source_height"]


def test_image_json_preview_squishes_tall_logo_to_full_width(
    tmp_path: Path,
) -> None:
    Image = pytest.importorskip("PIL.Image")
    repo = _seed_repo(tmp_path)
    image_path = tmp_path / "tall-logo.png"
    image = Image.new("RGB", (10, 100), (255, 255, 255))
    pixels = image.load()
    for y in range(0, 20):
        for x in range(10):
            pixels[x, y] = (220, 40, 40)
    for y in range(80, 100):
        for x in range(2, 8):
            pixels[x, y] = (20, 20, 20)
    image.save(image_path, format="PNG")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_main([
            "board", "art", "variant", "create",
            "--image", str(image_path),
            str(repo),
            "--display-name", "Hatch",
            "--seed", "image-tall-seed",
            "--json",
        ])

    assert rc == 0
    payload = json.loads(out.getvalue())
    assert payload["image"]["emoji_width"] == IMAGE_BLOCK_MAX_WIDTH
    assert payload["image"]["emoji_height"] == round(
        IMAGE_BLOCK_MAX_WIDTH / IMAGE_BLOCK_MIN_ASPECT_RATIO
    )
    assert payload["image"]["crop_left"] == 0
    assert payload["image"]["crop_right"] == payload["image"]["source_width"]
    assert payload["image"]["crop_top"] == 0
    assert payload["image"]["crop_bottom"] == payload["image"]["source_height"]

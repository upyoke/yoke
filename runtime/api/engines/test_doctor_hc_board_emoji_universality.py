"""Tests for HC-board-emoji-universality."""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines import doctor_hc_board_emoji_universality as emoji_hc
from yoke_core.engines.doctor_report import _resolve_repo_root


def test_live_board_sources_have_no_vs16_or_skintone() -> None:
    root = _resolve_repo_root()
    assert root, "repo root should resolve"
    hits = emoji_hc.scan_board_emoji(Path(root))
    assert hits == [], "non-universal emoji in board sources:\n" + "\n".join(hits)


def test_scan_flags_vs16_and_skintone(tmp_path: Path) -> None:
    board_rel, _ = emoji_hc._SCAN_DIR_GLOBS[0]
    board = tmp_path / board_rel
    board.mkdir(parents=True)
    # U+2764 + VS16 (heart) and thumbs-up + Fitzpatrick-6 skin tone.
    (board / "bad.py").write_text(
        'HEART = "❤️"\nHAND = "\U0001f44d\U0001f3ff"\n',
        encoding="utf-8",
    )
    hits = emoji_hc.scan_board_emoji(tmp_path)
    assert any("VS16" in h for h in hits), hits
    assert any("skin-tone" in h for h in hits), hits


def test_scan_flags_package_art_data(tmp_path: Path) -> None:
    data = tmp_path / emoji_hc._SCAN_EXTRA_FILES[0]
    data.parent.mkdir(parents=True)
    data.write_text("❤️ broken top border\n", encoding="utf-8")
    hits = emoji_hc.scan_board_emoji(tmp_path)
    assert any(str(emoji_hc._SCAN_EXTRA_FILES[0]) in h for h in hits), hits
    assert any("VS16" in h for h in hits), hits


def test_scan_ignores_universal_glyphs(tmp_path: Path) -> None:
    board_rel, _ = emoji_hc._SCAN_DIR_GLOBS[0]
    board = tmp_path / board_rel
    board.mkdir(parents=True)
    # Colored squares + circles + large square + box-drawing: all universal.
    (board / "ok.py").write_text(
        'A = "\U0001f7e8\U0001f535⬛"\nB = "border ║ block █"\n',
        encoding="utf-8",
    )
    assert emoji_hc.scan_board_emoji(tmp_path) == []

"""Interactive loop helpers for board-art variant creation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Tuple

from yoke_contracts.project_contract.board_art import (
    BoardArtVariant,
    generate_random_ascii_variant_detail,
    generate_random_image_mixed_variant_detail,
    generate_random_mixed_variant_detail,
)
from yoke_contracts.project_contract.board_art.image_to_emoji import ImageEmojiBlock


def _append_variant(path: Path, section: str, text: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not existing.endswith("\n\n"):
        existing += "\n"
    path.write_text(
        existing + f"## {section}\n\n{text.rstrip()}\n",
        encoding="utf-8",
    )


def _emit_variant(
    variant: BoardArtVariant,
    *,
    repo_root: Path,
    board_art_path: Path,
    max_width: int,
    json_mode: bool,
    applied: bool,
    image_block: ImageEmojiBlock | None = None,
    image_path: Path | None = None,
) -> None:
    if json_mode:
        payload = {
            "kind": variant.kind,
            "font": variant.font,
            "emoji_index": variant.emoji_index,
            "max_width": max_width,
            "repo_root": str(repo_root),
            "board_art_path": str(board_art_path),
            "applied": applied,
            "text": variant.text,
        }
        if image_block is not None:
            payload["emoji_source"] = "image"
            payload["image"] = {
                "path": str(image_path) if image_path is not None else None,
                "source_format": image_block.source_format,
                "source_width": image_block.source_width,
                "source_height": image_block.source_height,
                "crop_left": image_block.crop_left,
                "crop_top": image_block.crop_top,
                "crop_right": image_block.crop_right,
                "crop_bottom": image_block.crop_bottom,
                "cropped_width": image_block.cropped_width,
                "cropped_height": image_block.cropped_height,
                "emoji_width": image_block.width,
                "emoji_height": image_block.height,
                "emoji_cells": image_block.cells,
                "emoji_max_cells": image_block.max_cells,
                "emoji_text": image_block.text,
            }
        print(json.dumps(payload, ensure_ascii=False))
        return

    meta = [variant.kind]
    if variant.font:
        meta.append(f"font={variant.font}")
    if variant.emoji_index is not None:
        meta.append(f"emoji={variant.emoji_index}")
    if image_block is not None:
        label = image_path.name if image_path is not None else "image"
        meta.append(
            f"image={label} {image_block.width}x{image_block.height}"
        )
    print(f"\n--- {' '.join(meta)} ---")
    print(variant.text)
    print("---")



def _generate_ascii(
    display_name: str,
    *,
    seed_text: str,
    attempt: int,
    max_width: int,
    used_fonts: List[str],
) -> BoardArtVariant:
    variant = generate_random_ascii_variant_detail(
        display_name,
        seed_text=seed_text,
        attempt=attempt,
        max_width=max_width,
        used_fonts=used_fonts,
    )
    if variant.font:
        used_fonts.append(variant.font)
    return variant


def _generate_mixed(
    display_name: str,
    *,
    seed_text: str,
    attempt: int,
    max_width: int,
    used_fonts: List[str],
    used_pairs: List[Tuple[str, int]],
    used_emoji_indexes: List[int],
    fixed_emoji_column: str | None = None,
    keep_ascii: BoardArtVariant | None = None,
    keep_emoji: BoardArtVariant | None = None,
) -> BoardArtVariant:
    if fixed_emoji_column is not None:
        variant = generate_random_image_mixed_variant_detail(
            display_name,
            fixed_emoji_column,
            seed_text=seed_text,
            attempt=attempt,
            max_width=max_width,
            used_fonts=used_fonts,
        )
    else:
        variant = generate_random_mixed_variant_detail(
            display_name,
            seed_text=seed_text,
            attempt=attempt,
            max_width=max_width,
            used_fonts=used_fonts,
            used_pairs=used_pairs,
            used_emoji_indexes=used_emoji_indexes,
            keep_ascii_art=keep_ascii.ascii_art if keep_ascii else None,
            keep_font=keep_ascii.font if keep_ascii else None,
            keep_emoji_column=keep_emoji.emoji_column if keep_emoji else None,
            keep_emoji_index=keep_emoji.emoji_index if keep_emoji else None,
        )
    if variant.font:
        used_fonts.append(variant.font)
    if variant.font and variant.emoji_index is not None:
        used_pairs.append((variant.font, variant.emoji_index))
    if variant.emoji_index is not None:
        used_emoji_indexes.append(variant.emoji_index)
    return variant


def _interactive_loop(
    *,
    kind: str,
    display_name: str,
    seed_text: str,
    max_width: int,
    repo_root: Path,
    board_art_path: Path,
    json_mode: bool,
    fixed_emoji_column: str | None = None,
    image_block: ImageEmojiBlock | None = None,
    image_path: Path | None = None,
) -> int:
    attempt = 0
    used_fonts: List[str] = []
    used_pairs: List[Tuple[str, int]] = []
    used_emoji_indexes: List[int] = []

    def next_ascii() -> BoardArtVariant:
        nonlocal attempt
        variant = _generate_ascii(
            display_name,
            seed_text=seed_text,
            attempt=attempt,
            max_width=max_width,
            used_fonts=used_fonts,
        )
        attempt += 1
        return variant

    def next_mixed(
        *,
        keep_ascii: BoardArtVariant | None = None,
        keep_emoji: BoardArtVariant | None = None,
    ) -> BoardArtVariant:
        nonlocal attempt
        variant = _generate_mixed(
            display_name,
            seed_text=seed_text,
            attempt=attempt,
            max_width=max_width,
            used_fonts=used_fonts,
            used_pairs=used_pairs,
            used_emoji_indexes=used_emoji_indexes,
            fixed_emoji_column=fixed_emoji_column,
            keep_ascii=keep_ascii,
            keep_emoji=keep_emoji,
        )
        attempt += 1
        return variant

    if kind == "ASCII":
        variant = next_ascii()
    elif kind == "Emoji":
        variant = BoardArtVariant(
            kind="Emoji",
            text=fixed_emoji_column or "",
            word=display_name,
            emoji_column=fixed_emoji_column,
        )
    else:
        variant = next_mixed()
    while True:
        _emit_variant(
            variant,
            repo_root=repo_root,
            board_art_path=board_art_path,
            max_width=max_width,
            json_mode=json_mode,
            applied=False,
            image_block=image_block,
            image_path=image_path,
        )
        if kind == "ASCII":
            choice = input("[a]pply, [g]enerate another, [s]kip > ").strip().lower()
            if choice in ("a", "apply"):
                _append_variant(board_art_path, kind, variant.text)
                print(f"Applied {kind} variant to {board_art_path}")
                return 0
            if choice in ("g", "generate", "another", ""):
                variant = next_ascii()
                continue
            if choice in ("s", "skip", "q", "quit"):
                print("Skipped; board-art unchanged.")
                return 0
        elif kind == "Emoji":
            choice = input("[a]pply, [s]kip > ").strip().lower()
            if choice in ("a", "apply"):
                _append_variant(board_art_path, kind, variant.text)
                print(f"Applied {kind} variant to {board_art_path}")
                return 0
            if choice in ("s", "skip", "q", "quit"):
                print("Skipped; board-art unchanged.")
                return 0
        elif fixed_emoji_column is not None:
            choice = input(
                "[a]pply, [g]enerate another font, [s]kip > "
            ).strip().lower()
            if choice in ("a", "apply"):
                _append_variant(board_art_path, kind, variant.text)
                print(f"Applied {kind} variant to {board_art_path}")
                return 0
            if choice in ("g", "generate", "another", ""):
                variant = next_mixed()
                continue
            if choice in ("s", "skip", "q", "quit"):
                print("Skipped; board-art unchanged.")
                return 0
        else:
            choice = input(
                "[a]pply, [g]enerate another, keep [x] ASCII, "
                "keep [e]moji, [s]kip > "
            ).strip().lower()
            if choice in ("a", "apply"):
                _append_variant(board_art_path, kind, variant.text)
                print(f"Applied {kind} variant to {board_art_path}")
                return 0
            if choice in ("g", "generate", "another", ""):
                variant = next_mixed()
                continue
            if choice in ("x", "ascii", "keep ascii", "text"):
                variant = next_mixed(keep_ascii=variant)
                continue
            if choice in ("e", "emoji", "keep emoji"):
                variant = next_mixed(keep_emoji=variant)
                continue
            if choice in ("s", "skip", "q", "quit"):
                print("Skipped; board-art unchanged.")
                return 0
        print("Choose one of the listed options.", file=sys.stderr)

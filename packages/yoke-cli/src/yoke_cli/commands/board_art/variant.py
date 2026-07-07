"""Tool-shaped ``yoke board art variant create`` command.

This command is intentionally client-local: it reads and optionally edits the
current checkout's ``.yoke/board-art`` file. The generator itself lives in
``yoke_contracts.project_contract.board_art`` so deterministic install and future
onboarding can reuse the same width-bounded variant behavior.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.git_hook import AdapterFn
from yoke_cli.commands.board_art.loop import (
    _append_variant,
    _emit_variant,
    _interactive_loop,
)
from yoke_cli.commands.board_art.image import (
    IMAGE_ONLY_VISUAL_WIDTH_THRESHOLD,
    IMAGE_SQUISH_ASPECT_THRESHOLD,
    build_image_variant,
)
from yoke_contracts.project_contract.board_art import (
    DEFAULT_VARIANT_MAX_WIDTH,
    generate_random_ascii_variant_detail,
    generate_random_mixed_variant_detail,
)
from yoke_contracts.project_contract.board_art.image_to_emoji import (
    IMAGE_BLOCK_MAX_AREA_RATIO,
    IMAGE_BLOCK_MAX_ASPECT_RATIO,
    IMAGE_BLOCK_MAX_HEIGHT,
    IMAGE_BLOCK_MIN_ASPECT_RATIO,
)

BOARD_ART_VARIANT_CREATE_USAGE = (
    "yoke board art variant create (--ascii | --mixed | --image IMAGE) "
    "[REPO_ROOT] [--display-name NAME] [--max-width N] [--seed TEXT] "
    "[--image-max-area-ratio N] [--image-min-width N] [--image-max-width N] "
    "[--image-min-height N] [--image-max-height N] [--image-min-aspect N] "
    "[--image-max-aspect N] [--apply] [--json]"
)

_HELP_DEEP = f"""\
Generate one random board-art variant, print it in the terminal, and either
append it to .yoke/board-art or reroll. Mixed variants can keep the ASCII
side while rerolling emoji, or keep the emoji side while rerolling ASCII.
Image-backed variants pair the display name with an emoji grid generated from
the supplied PNG/JPEG; wide translated images render as standalone Emoji
variants so the image keeps the available width.

Examples:

  yoke board art variant create --ascii
  yoke board art variant create --mixed --display-name Buzz
  yoke board art variant create --image ./logo.png --display-name Buzz
  yoke board art variant create --mixed ~/code/app --apply

All generated variants must fit within --max-width. The default max width is
{DEFAULT_VARIANT_MAX_WIDTH} visual cells. For --image, the generated emoji grid
defaults to a {IMAGE_BLOCK_MAX_HEIGHT}-cell short side,
switches to image-only above {IMAGE_ONLY_VISUAL_WIDTH_THRESHOLD} visual
columns, squeezes sources wider or taller than
{IMAGE_SQUISH_ASPECT_THRESHOLD:g}:1 without cropping, and accepts aspect ratio
{IMAGE_BLOCK_MIN_ASPECT_RATIO:g} to {IMAGE_BLOCK_MAX_ASPECT_RATIO:g}."""


def _find_board_art_root(raw_root: str | None) -> Path:
    start = Path(raw_root or ".").expanduser().resolve()
    if start.is_file():
        start = start.parent
    for candidate in (start, *start.parents):
        if (candidate / ".yoke" / "board-art").exists():
            return candidate
    return start


def _board_art_path(repo_root: Path) -> Path:
    return repo_root / ".yoke" / "board-art"


def _display_name(parsed: argparse.Namespace, repo_root: Path) -> str:
    return parsed.display_name.strip() if parsed.display_name else repo_root.name


def board_art_variant_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke board art variant create",
        description=f"{BOARD_ART_VARIANT_CREATE_USAGE}\n\n{_HELP_DEEP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--ascii", action="store_true", help="Generate an ASCII variant."
    )
    mode.add_argument(
        "--mixed", action="store_true", help="Generate a Mixed variant."
    )
    mode.add_argument(
        "--image",
        metavar="PATH",
        help=(
            "Generate a Mixed variant from a PNG/JPEG image: random ASCII "
            "plus the image-derived emoji grid."
        ),
    )
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=None,
        help="Repository root, or any child path under one.",
    )
    parser.add_argument(
        "--display-name",
        default=None,
        help="Project display name to render (default: repo directory name).",
    )
    parser.add_argument(
        "--max-width",
        type=int,
        default=DEFAULT_VARIANT_MAX_WIDTH,
        help="Reject full generated variants above this visual width.",
    )
    parser.add_argument(
        "--image-max-area-ratio",
        type=float,
        default=IMAGE_BLOCK_MAX_AREA_RATIO,
        help=(
            "Optional maximum image emoji-grid area as a fraction of "
            "master-map area."
        ),
    )
    parser.add_argument(
        "--image-min-width",
        type=int,
        default=None,
        help=(
            "Optional minimum image emoji-grid width in cells. Defaults from "
            "the source orientation for --image."
        ),
    )
    parser.add_argument(
        "--image-max-width",
        type=int,
        default=None,
        help="Optional maximum image emoji-grid width in cells.",
    )
    parser.add_argument(
        "--image-min-height",
        type=int,
        default=None,
        help=(
            "Optional minimum image emoji-grid height in cells. Defaults from "
            "the source orientation for --image."
        ),
    )
    parser.add_argument(
        "--image-max-height",
        type=int,
        default=None,
        help="Optional maximum image emoji-grid height in cells.",
    )
    parser.add_argument(
        "--image-min-aspect",
        type=float,
        default=IMAGE_BLOCK_MIN_ASPECT_RATIO,
        help="Minimum accepted image emoji-grid aspect ratio.",
    )
    parser.add_argument(
        "--image-max-aspect",
        type=float,
        default=IMAGE_BLOCK_MAX_ASPECT_RATIO,
        help="Maximum accepted image emoji-grid aspect ratio.",
    )
    parser.add_argument(
        "--seed",
        default=None,
        help="Optional deterministic seed for reproducible random selection.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Append the first generated variant without prompting.",
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, BOARD_ART_VARIANT_CREATE_USAGE)
    if parsed is None:
        return 2
    if parsed.max_width <= 0:
        print("yoke board art variant create: --max-width must be positive",
              file=sys.stderr)
        return 2

    repo_root = _find_board_art_root(parsed.repo_root)
    board_art_path = _board_art_path(repo_root)
    if not board_art_path.exists():
        print(
            "yoke board art variant create: no .yoke/board-art found under "
            f"{repo_root}",
            file=sys.stderr,
        )
        return 2

    kind = "ASCII" if parsed.ascii else "Mixed"
    seed_text = parsed.seed or secrets.token_hex(16)
    display_name = _display_name(parsed, repo_root)
    image_block = None
    image_path = None
    if kind == "ASCII":
        variant = generate_random_ascii_variant_detail(
            display_name,
            seed_text=seed_text,
            attempt=0,
            max_width=parsed.max_width,
        )
    elif parsed.image:
        image_path = Path(parsed.image).expanduser()
        try:
            kind, variant, image_block = build_image_variant(
                image_path=image_path,
                board_art_path=board_art_path,
                display_name=display_name,
                seed_text=seed_text,
                max_width=parsed.max_width,
                image_max_area_ratio=parsed.image_max_area_ratio,
                image_min_width=parsed.image_min_width,
                image_max_width=parsed.image_max_width,
                image_min_height=parsed.image_min_height,
                image_max_height=parsed.image_max_height,
                image_min_aspect=parsed.image_min_aspect,
                image_max_aspect=parsed.image_max_aspect,
            )
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            print(f"yoke board art variant create: {exc}", file=sys.stderr)
            return 2
    else:
        variant = generate_random_mixed_variant_detail(
            display_name,
            seed_text=seed_text,
            attempt=0,
            max_width=parsed.max_width,
        )

    if parsed.apply:
        _append_variant(board_art_path, kind, variant.text)
        _emit_variant(
            variant,
            repo_root=repo_root,
            board_art_path=board_art_path,
            max_width=parsed.max_width,
            json_mode=parsed.json_mode,
            applied=True,
            image_block=image_block,
            image_path=image_path,
        )
        if not parsed.json_mode:
            print(f"Applied {kind} variant to {board_art_path}")
        return 0

    if not sys.stdin.isatty():
        _emit_variant(
            variant,
            repo_root=repo_root,
            board_art_path=board_art_path,
            max_width=parsed.max_width,
            json_mode=parsed.json_mode,
            applied=False,
            image_block=image_block,
            image_path=image_path,
        )
        if not parsed.json_mode:
            print("Not applied; rerun in a TTY or pass --apply.")
        return 0

    return _interactive_loop(
        kind=kind,
        display_name=display_name,
        seed_text=seed_text,
        max_width=parsed.max_width,
        repo_root=repo_root,
        board_art_path=board_art_path,
        json_mode=parsed.json_mode,
        fixed_emoji_column=image_block.text if image_block else None,
        image_block=image_block,
        image_path=image_path,
    )


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("board", "art", "variant", "create"): board_art_variant_create,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke board art variant create --ascii|--mixed|--image PATH": (
        "Generate a width-bounded random ASCII, Mixed, or image-backed "
        "board-art variant, preview it, and optionally append it to "
        ".yoke/board-art."
    ),
}


__all__ = [
    "BOARD_ART_VARIANT_CREATE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "board_art_variant_create",
]

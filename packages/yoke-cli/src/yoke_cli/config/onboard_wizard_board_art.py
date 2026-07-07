"""Pure board-art helpers for the onboard wizard's :class:`BoardArtFlow`.

No Textual, no app state — variant generation, the simulated-progress render,
the apply-time ``.yoke/board-art`` write, and the small presentational helpers
live here so the flow mixin stays a thin navigation layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from yoke_cli.config.onboard_wizard_widgets import SelectionRow
from yoke_contracts.project_contract.board_art import (
    DEFAULT_VARIANT_MAX_WIDTH,
    generate_random_ascii_variant_detail,
    generate_random_image_mixed_variant_detail,
    generate_random_mixed_variant_detail,
)
from yoke_contracts.project_contract.board_art.config_paths import (
    board_art_path_for_config,
)

# A representative mid-flight board. A freshly onboarded project has no items
# yet, so the preview and payoff render the frontier fill against these example
# counts to show what the board looks like once work is moving.
_SIMULATED_TOTAL = 40
_SIMULATED_FRONTIER_COUNTS = {
    "done": 18,
    "release": 2,
    "implemented": 1,
    "reviewing": 2,
    "implementing": 3,
    "blocked": 1,
    "refined": 4,
    "planning": 4,
    "idea": 5,
    "total": _SIMULATED_TOTAL,
}
_SIMULATED_STATS_COUNTS = {
    "active": 5,
    "pipeline": 8,
    "backlog": 5,
    "blocked": 1,
    "done": 21,
    "frozen": 0,
}


def generate_variant(
    *, kind: str, word: str, seed_text: str | None, attempt: int,
    image_column: str | None = None,
) -> Any:
    """Generate one header variant for the current draft (ASCII / Mixed /
    image-backed Mixed). ``word`` is passed through so onboarding's customize
    text and the master-map default both bypass the auto-chosen project word."""
    if kind == "ASCII":
        return generate_random_ascii_variant_detail(
            word=word, seed_text=seed_text, attempt=attempt,
            max_width=DEFAULT_VARIANT_MAX_WIDTH,
        )
    if image_column is not None:
        return generate_random_image_mixed_variant_detail(
            "", image_column, word=word, seed_text=seed_text, attempt=attempt,
            max_width=DEFAULT_VARIANT_MAX_WIDTH,
        )
    return generate_random_mixed_variant_detail(
        word=word, seed_text=seed_text, attempt=attempt,
        max_width=DEFAULT_VARIANT_MAX_WIDTH,
    )


def build_image(
    *, path: Path, word: str, seed_text: str | None, master_map_word: str,
) -> tuple[str, Any, str]:
    """Convert an image to a variant. Returns ``(kind, variant, emoji_column)``.

    Raises on an unreadable/unsupported/too-wide image — callers route the
    message to a retry view.
    """
    from yoke_cli.commands.board_art.image import build_image_variant
    from yoke_contracts.project_contract.board_art.image_to_emoji import (
        IMAGE_BLOCK_MAX_ASPECT_RATIO,
        IMAGE_BLOCK_MIN_ASPECT_RATIO,
    )
    from yoke_contracts.project_contract.board_art.render_seed import (
        _master_map_lines,
    )

    kind, variant, block = build_image_variant(
        image_path=path,
        board_art_path=None,
        master_map=_master_map_lines(master_map_word),
        display_name="",
        word=word,
        seed_text=seed_text,
        max_width=DEFAULT_VARIANT_MAX_WIDTH,
        image_max_area_ratio=None,
        image_min_width=None,
        image_max_width=None,
        image_min_height=None,
        image_max_height=None,
        image_min_aspect=IMAGE_BLOCK_MIN_ASPECT_RATIO,
        image_max_aspect=IMAGE_BLOCK_MAX_ASPECT_RATIO,
    )
    return kind, variant, block.text


def friendly_image_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return f"{text}. Try a PNG or JPG, or pick a different image."


def preview_title(kind: str, is_image: bool) -> str:
    if is_image:
        return "Here's your image as board art."
    if kind == "ASCII":
        return "Here's an ASCII header."
    return "Here's a Mixed header."


def preview_meta(variant: Any, image_path: str | None) -> str | None:
    bits = []
    if getattr(variant, "font", None):
        bits.append(f"font: {variant.font}")
    if getattr(variant, "emoji_index", None) is not None:
        bits.append(f"column #{variant.emoji_index}")
    if image_path:
        bits.append(Path(image_path).name)
    return " · ".join(bits) or None


def preview_rows(kind: str, is_image: bool) -> list[SelectionRow]:
    rows = [SelectionRow("save", "Save to board", "keep this one")]
    if kind != "Emoji":
        shuffle_hint = (
            "another font" if (kind == "ASCII" or is_image) else "new font + emoji"
        )
        rows.append(SelectionRow("shuffle", "Shuffle", shuffle_hint))
        rows.append(
            SelectionRow("customize", "Customize text", "render different letters")
        )
    if is_image:
        rows.append(SelectionRow("reimage", "Pick a different image", ""))
    rows.append(SelectionRow("back", "Back to styles", ""))
    return rows


def render_master_map(word: str) -> str:
    """Render the master map with a simulated frontier fill (preview + payoff).

    The frontier renderer lives in the shipped ``yoke_contracts.board`` tier,
    so this renders identically on any install (core present or not) and on any
    managed project — no dynamic core reach, no degraded fallback.
    """
    from yoke_contracts.board.art_render import render_header
    from yoke_contracts.board.config import BoardConfig
    from yoke_contracts.project_contract.board_art.config import ArtConfig
    from yoke_contracts.project_contract.board_art.render_seed import (
        _master_map_lines,
    )

    lines = _master_map_lines(word)
    return render_header(
        None, BoardConfig(), ArtConfig(master_map=lines),
        "frontier", None, _SIMULATED_FRONTIER_COUNTS,
        stats_counts=_SIMULATED_STATS_COUNTS,
        stats_total=_SIMULATED_TOTAL,
        seed=0,
    )


def repo_root_from_report(report: Any, fallback_checkout: str | None) -> Path | None:
    checkout = None
    if isinstance(report, dict):
        onboarding = report.get("project_onboarding")
        if isinstance(onboarding, dict):
            checkout = onboarding.get("checkout")
            if isinstance(checkout, Mapping):
                checkout = checkout.get("path")
    checkout = checkout or fallback_checkout
    if not checkout:
        return None
    return Path(str(checkout)).expanduser()


def board_art_exists(repo_root: str | Path | None) -> bool:
    """Return whether the checkout already has project-local board art."""
    if not repo_root:
        return False
    return board_art_path_for_config(None, repo_root=str(repo_root)).is_file()


def write_board_art(repo_root: Path, word: str, variants: list[Any]) -> None:
    """Write the chosen master map + header variants to ``.yoke/board-art``."""
    from yoke_contracts.project_contract.board_art.config import BLACK, WHITE
    from yoke_contracts.project_contract.board_art.config_paths import (
        board_art_path_for_config,
    )
    from yoke_contracts.project_contract.board_art.render_seed import (
        _ART_HEADER,
        _master_map_lines,
    )

    art_path = board_art_path_for_config(None, repo_root=str(repo_root))
    parts = [
        _ART_HEADER.format(white=WHITE, black=BLACK),
        "## Master Map",
        "",
        "\n".join(_master_map_lines(word)),
    ]
    for variant in variants:
        parts.extend(("", f"## {variant.kind}", "", variant.text.rstrip()))
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")


def rebuild_board(repo_root: Path) -> Path:
    """Rebuild the project's initial BOARD.md and return the written path."""
    from yoke_cli.board import rebuild as board_rebuild_flow

    resolved_repo_root = board_rebuild_flow.resolve_main_repo_root(str(repo_root))
    board_path = board_rebuild_flow.resolve_board_path(resolved_repo_root, None)
    result = board_rebuild_flow.rebuild(
        repo_arg=str(resolved_repo_root),
        force=True,
        emit=False,
    )
    if int(result.exit_code) != 0:
        detail = result.message or f"board rebuild exited with {result.exit_code}"
        raise RuntimeError(detail)
    if not board_path.is_file():
        raise RuntimeError(f"board rebuild did not write {board_path}")
    return board_path


__all__ = [
    "build_image",
    "board_art_exists",
    "friendly_image_error",
    "generate_variant",
    "preview_meta",
    "preview_rows",
    "preview_title",
    "rebuild_board",
    "render_master_map",
    "repo_root_from_report",
    "write_board_art",
]

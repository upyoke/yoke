"""Preview render helpers for the board CLI ``preview`` subcommand.

These helpers compose a single preview frame (`_preview_render_one`),
resolve named variants (`_resolve_named_variant`), and render the
exhaustive ``--all`` gallery (`_preview_all`). They are imported by
``yoke_core.board.preview`` and are not used outside the preview
family.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from yoke_contracts.board.art import (
    ArtConfig,
    ArtVariant,
    render_header,
)
from yoke_contracts.board.config import BoardConfig
from yoke_core.board.preview_mock import _mock_dashboard


def _preview_render_one(
    label: str,
    art_config: ArtConfig,
    config: BoardConfig,
    mode: str,
    variant: Optional[ArtVariant],
    frontier_counts: Dict[str, int],
    seed: Optional[int],
    dashboard: bool = False,
    velocity_meter: bool = False,
) -> str:
    """Render a single preview variant to string."""
    parts: List[str] = []

    if label:
        parts.append(f"--- {label} ---")

    header = render_header(
        db=None,
        config=config,
        art_config=art_config,
        mode=mode,
        variant=variant,
        frontier_counts=frontier_counts,
        seed=seed,
    )
    if header:
        parts.append(header)

    if dashboard:
        parts.append(_mock_dashboard(velocity_meter=velocity_meter))

    parts.append("")
    return "\n".join(parts)


def _resolve_named_variant(
    name: str,
    art_config: ArtConfig,
    fc: Dict[str, int],
) -> "tuple[str, Optional[ArtVariant]]":
    """Resolve a variant name to (mode, ArtVariant|None)."""
    if name == "frontier":
        fc_frontier = dict(fc)
        fc_frontier.update(
            done=40, implemented=5, release=3, reviewing=4,
            implementing=12, active=12, blocked=2, refined=8,
            idea=6, total=80, pipeline=8, backlog=6,
        )
        fc.update(fc_frontier)
        return "frontier", None

    if name.startswith("rainbow_"):
        return name, None

    if name.startswith("emoji_"):
        idx = int(name.split("_")[1]) - 1
        if 0 <= idx < len(art_config.emoji_variants):
            return name, art_config.emoji_variants[idx]
        return "rainbow_random", None

    if name.startswith("ascii_"):
        idx = int(name.split("_")[1]) - 1
        if 0 <= idx < len(art_config.ascii_variants):
            return name, art_config.ascii_variants[idx]
        return "rainbow_random", None

    if name.startswith("mixed_"):
        idx = int(name.split("_")[1]) - 1
        if 0 <= idx < len(art_config.mixed_variants):
            return name, art_config.mixed_variants[idx]
        return "rainbow_random", None

    return "rainbow_random", None


def _preview_all(
    art_config: ArtConfig,
    config: BoardConfig,
    fc: Dict[str, int],
    seed: Optional[int],
    velocity_meter: bool,
) -> List[str]:
    """Render all variants for --all mode."""
    parts: List[str] = []

    # Progress fills
    parts.append("=== Master Map: Progress Fill Previews ===")
    parts.append("")
    for pct in [0, 25, 50, 75, 100]:
        total_cells = 251
        done_n = pct * total_cells // 100
        fc_pct = dict(fc)
        fc_pct["done"] = done_n
        fc_pct["total"] = total_cells
        fc_pct["idea"] = total_cells - done_n
        fc_pct["backlog"] = fc_pct["idea"]
        parts.append(_preview_render_one(
            f"Progress: {pct}% ({done_n}/{total_cells} W-cells)",
            art_config, config, "frontier", None, fc_pct, seed,
        ))

    # Rainbow modes
    parts.append("=== Master Map: Rainbow Modes (1-5) ===")
    parts.append("")
    rm_labels = {
        "1": "Mode 1: Pure Random",
        "2": "Mode 2: Per-Letter Colors",
        "3": "Mode 3: Half-Letter Colors",
        "4": "Mode 4: Gradient Background",
        "5": "Mode 5: Emoji",
    }
    rm_modes = {
        "1": "rainbow_random",
        "2": "rainbow_letters",
        "3": "rainbow_halves",
        "4": "rainbow_gradient",
        "5": "rainbow_emoji",
    }
    for k in ["1", "2", "3", "4", "5"]:
        parts.append(_preview_render_one(
            rm_labels[k], art_config, config,
            rm_modes[k], None, fc, seed,
        ))

    # Emoji variants
    n_emoji = len(art_config.emoji_variants)
    parts.append(f"=== Emoji Variants (1-{n_emoji}) ===")
    parts.append("")
    for i, v in enumerate(art_config.emoji_variants, 1):
        parts.append(_preview_render_one(
            f"Emoji {i}", art_config, config,
            f"emoji_{i}", v, fc, seed,
        ))

    # ASCII variants
    n_ascii = len(art_config.ascii_variants)
    if n_ascii > 0:
        parts.append(f"=== ASCII Variants (1-{n_ascii}) ===")
        parts.append("")
        for i, v in enumerate(art_config.ascii_variants, 1):
            parts.append(_preview_render_one(
                f"ASCII {i}", art_config, config,
                f"ascii_{i}", v, fc, seed,
            ))

    # Mixed variants
    n_mixed = len(art_config.mixed_variants)
    if n_mixed > 0:
        parts.append(f"=== Mixed Variants (1-{n_mixed}) ===")
        parts.append("")
        for i, v in enumerate(art_config.mixed_variants, 1):
            parts.append(_preview_render_one(
                f"Mixed {i}", art_config, config,
                f"mixed_{i}", v, fc, seed,
            ))

    # Dashboard preview
    parts.append("=== Dashboard Preview ===")
    parts.append("")
    fc_half = dict(fc)
    fc_half["done"] = 125
    fc_half["total"] = 251
    fc_half["idea"] = 126
    fc_half["backlog"] = 126
    parts.append(_preview_render_one(
        "50% Progress + Dashboard",
        art_config, config, "frontier", None, fc_half, seed,
        dashboard=True, velocity_meter=velocity_meter,
    ))

    return parts

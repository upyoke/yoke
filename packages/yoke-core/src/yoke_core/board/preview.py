"""Preview subcommand handler for ``python3 -m yoke_core.board preview``.

The CLI wiring lives in ``yoke_core.board.__main__``. The dispatcher
calls ``_preview_main`` here with the parsed argparse namespace; this
module owns the mode-selection logic and prints the rendered preview.
Render helpers live in ``yoke_core.board.preview_modes`` and mock
dashboard data lives in ``yoke_core.board.preview_mock``.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from typing import Dict, List

from yoke_contracts.board.art import ArtConfig, parse_art_config
from yoke_contracts.board.config import BoardConfig, parse_config
from yoke_core.board.db import BoardDB
from yoke_core.board.preview_modes import (
    _preview_all,
    _preview_render_one,
    _resolve_named_variant,
)
from yoke_contracts.board.zen import render_zen_widget


def _preview_main(args: argparse.Namespace) -> int:
    """Handle preview subcommand."""
    config_path = args.config or ""
    repo_root = getattr(args, "repo_root", None)
    if config_path and os.path.isfile(config_path):
        config = parse_config(config_path, repo_root=repo_root)
        art_config = parse_art_config(config_path, repo_root=repo_root)
    else:
        config = parse_config(None, repo_root=repo_root) if repo_root else BoardConfig()
        art_config = (
            parse_art_config(None, repo_root=repo_root) if repo_root else ArtConfig()
        )

    seed = args.seed

    # Parse stats
    stat_a = args.stat_active or 0
    stat_p = args.stat_pipeline or 0
    stat_b = args.stat_backlog or 0
    stat_d = args.stat_done or 0
    stat_f = args.stat_frozen or 0
    # blocked stat row in the preview stats box; defaults to 0
    # so existing preview invocations continue to render with no Blocked row.
    stat_bk = getattr(args, "stat_blocked", 0) or 0

    if args.stats:
        parts = args.stats.split(",")
        if len(parts) >= 1:
            stat_a = int(parts[0])
        if len(parts) >= 2:
            stat_p = int(parts[1])
        if len(parts) >= 3:
            stat_b = int(parts[2])
        if len(parts) >= 4:
            stat_d = int(parts[3])
        if len(parts) >= 5:
            stat_f = int(parts[4])
        if len(parts) >= 6:
            stat_bk = int(parts[5])

    stat_total = stat_a + stat_p + stat_b + stat_d + stat_f + stat_bk

    # Build frontier_counts dict from stats (used by art header for stats box)
    fc: Dict[str, int] = {
        "done": stat_d,
        "implemented": 0,
        "release": 0,
        "reviewing": 0,
        "implementing": stat_a,
        "active": stat_a,
        "blocked": stat_bk,
        "refined": stat_p,
        "planning": 0,
        "idea": stat_b,
        "total": stat_total,
        "frozen": stat_f,
        "pipeline": stat_p,
        "backlog": stat_b,
    }

    dashboard = args.dashboard
    velocity_meter = args.velocity_meter
    mode_name = args.mode

    output_parts: List[str] = []

    if mode_name == "rainbow":
        mode_sel = "rainbow_random"
        header = _preview_render_one(
            "", art_config, config, mode_sel, None, fc, seed,
            dashboard, velocity_meter,
        )
        output_parts.append(header)

    elif mode_name == "rainbow-mode":
        rm_map = {
            "1": "rainbow_random",
            "2": "rainbow_letters",
            "3": "rainbow_halves",
            "4": "rainbow_gradient",
            "5": "rainbow_emoji",
        }
        rm_key = str(args.rainbow_mode)
        if rm_key not in rm_map:
            print(f"Error: mode must be 1-5", file=sys.stderr)
            return 1
        mode_sel = rm_map[rm_key]
        header = _preview_render_one(
            f"Rainbow mode {rm_key}", art_config, config,
            mode_sel, None, fc, seed,
            dashboard, velocity_meter,
        )
        output_parts.append(header)

    elif mode_name == "rainbow-all":
        output_parts.append("=== Rainbow Modes (1-5) ===")
        output_parts.append("")
        labels = {
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
            header = _preview_render_one(
                labels[k], art_config, config,
                rm_modes[k], None, fc, seed,
                dashboard, velocity_meter,
            )
            output_parts.append(header)

    elif mode_name == "progress":
        done_n = args.done_count or 0
        active_n = args.active_count or 0
        total_n = args.total_count or 10
        fc_prog = dict(fc)
        fc_prog["done"] = done_n
        fc_prog["implementing"] = active_n
        fc_prog["active"] = active_n
        fc_prog["total"] = total_n
        # Distribute remaining as idea
        used = done_n + active_n
        fc_prog["idea"] = max(0, total_n - used)
        fc_prog["backlog"] = fc_prog["idea"]
        header = _preview_render_one(
            "", art_config, config, "frontier", None, fc_prog, seed,
            dashboard, velocity_meter,
        )
        output_parts.append(header)

    elif mode_name == "percent":
        pct = args.percent_val or 50
        total_cells = 251
        done_n = pct * total_cells // 100
        fc_pct = dict(fc)
        fc_pct["done"] = done_n
        fc_pct["total"] = total_cells
        fc_pct["idea"] = total_cells - done_n
        fc_pct["backlog"] = fc_pct["idea"]
        header = _preview_render_one(
            f"Progress: {pct}% ({done_n}/{total_cells} W-cells filled)",
            art_config, config, "frontier", None, fc_pct, seed,
            dashboard, velocity_meter,
        )
        output_parts.append(header)

    elif mode_name == "variant":
        v_idx = args.variant_num
        if v_idx is not None and 1 <= v_idx <= len(art_config.emoji_variants):
            variant = art_config.emoji_variants[v_idx - 1]
            header = _preview_render_one(
                f"Emoji {v_idx}", art_config, config,
                f"emoji_{v_idx}", variant, fc, seed,
                dashboard, velocity_meter,
            )
            output_parts.append(header)
        else:
            n = len(art_config.emoji_variants)
            print(f"Error: Emoji variant {v_idx} out of range (1-{n})", file=sys.stderr)
            return 1

    elif mode_name == "named-variant":
        vname = args.variant_name or ""
        # Resolve variant name to mode + ArtVariant
        mode_sel, variant = _resolve_named_variant(vname, art_config, fc)
        header = _preview_render_one(
            vname, art_config, config, mode_sel, variant, fc, seed,
            dashboard, velocity_meter,
        )
        output_parts.append(header)

    elif mode_name == "ascii":
        a_idx = args.ascii_num
        if a_idx is not None and 1 <= a_idx <= len(art_config.ascii_variants):
            variant = art_config.ascii_variants[a_idx - 1]
            header = _preview_render_one(
                f"ASCII {a_idx}", art_config, config,
                f"ascii_{a_idx}", variant, fc, seed,
                dashboard, velocity_meter,
            )
            output_parts.append(header)
        else:
            n = len(art_config.ascii_variants)
            print(f"Error: ASCII variant {a_idx} out of range (1-{n})", file=sys.stderr)
            return 1

    elif mode_name == "mixed":
        m_idx = args.mixed_num
        if m_idx is not None and 1 <= m_idx <= len(art_config.mixed_variants):
            variant = art_config.mixed_variants[m_idx - 1]
            header = _preview_render_one(
                f"Mixed {m_idx}", art_config, config,
                f"mixed_{m_idx}", variant, fc, seed,
                dashboard, velocity_meter,
            )
            output_parts.append(header)
        else:
            n = len(art_config.mixed_variants)
            print(f"Error: Mixed variant {m_idx} out of range (1-{n})", file=sys.stderr)
            return 1

    elif mode_name == "zen":
        output_parts.append("=== Project Timelines Widget ===")
        output_parts.append("")
        try:
            preview_config = replace(config, timeline_widget="always")
            with BoardDB(args.db) as db:
                output_parts.extend(
                    render_zen_widget(db, preview_config, "all", 0, 0, 0)
                )
        except Exception as exc:
            output_parts.append(f"(zen widget unavailable: {exc})")

    elif mode_name == "all":
        output_parts.extend(_preview_all(
            art_config, config, fc, seed, velocity_meter,
        ))

    else:
        # Default: rainbow
        header = _preview_render_one(
            "", art_config, config, "rainbow_random", None, fc, seed,
            dashboard, velocity_meter,
        )
        output_parts.append(header)

    print("\n".join(output_parts))
    return 0

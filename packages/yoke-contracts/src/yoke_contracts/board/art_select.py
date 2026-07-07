"""Art selection — pick a mode and optional variant.

Top-level entry is :func:`select_art`; the private helpers
``_resolve_override``, ``_select_rainbow``, and ``_select_variant`` are
imported by tests.
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

from yoke_contracts.project_contract.board_art.config import ArtConfig, ArtVariant, RAINBOW_SUB_MODES
from yoke_contracts.board.config import BoardConfig


def select_art(
    config: BoardConfig,
    art_config: ArtConfig,
    seed: Optional[int] = None,
) -> Tuple[str, Optional[ArtVariant]]:
    """Select art mode and optional variant.

    Returns ``(mode_name, variant_or_none)`` where *mode_name* is one of:
    ``frontier``, ``rainbow_random``, ``rainbow_letters``, ``rainbow_halves``,
    ``rainbow_gradient``, ``rainbow_emoji``, ``emoji_N``, ``ascii_N``, ``mixed_N``.

    When *seed* is provided, selection is fully deterministic.
    """
    rng = random.Random(seed)

    emoji_count = len(art_config.emoji_variants)
    ascii_count = len(art_config.ascii_variants)
    mixed_count = len(art_config.mixed_variants)

    # --- art_override takes priority ---
    if config.art_override:
        result = _resolve_override(config.art_override, art_config)
        if result is not None:
            return result
        # Invalid override — fall through to weighted selection

    # --- bucket weights ---
    w_rainbow = config.art_weight_rainbow
    w_emoji = config.art_weight_emoji if emoji_count > 0 else 0
    w_ascii = config.art_weight_ascii if ascii_count > 0 else 0
    w_mixed = config.art_weight_mixed if mixed_count > 0 else 0
    w_frontier = config.art_weight_frontier

    total = w_rainbow + w_emoji + w_ascii + w_mixed + w_frontier

    if total <= 0:
        # Zero-weight fallback
        w_rainbow, w_emoji, w_ascii, w_mixed, w_frontier = 40, 45, 10, 5, 0
        if emoji_count <= 0:
            w_emoji = 0
        if ascii_count <= 0:
            w_ascii = 0
        if mixed_count <= 0:
            w_mixed = 0
        total = w_rainbow + w_emoji + w_ascii + w_mixed + w_frontier
        if total <= 0:
            return ("rainbow_random", None)

    pick = rng.randrange(total)
    cum = 0
    bucket = "rainbow"
    for name, w in [
        ("rainbow", w_rainbow),
        ("emoji", w_emoji),
        ("ascii", w_ascii),
        ("mixed", w_mixed),
        ("frontier", w_frontier),
    ]:
        if w <= 0:
            continue
        cum += w
        if pick < cum:
            bucket = name
            break

    # --- variant within bucket ---
    if bucket == "frontier":
        return ("frontier", None)

    if bucket == "rainbow":
        return _select_rainbow(config, rng)

    variants: List[ArtVariant]
    if bucket == "emoji":
        variants = art_config.emoji_variants
    elif bucket == "ascii":
        variants = art_config.ascii_variants
    else:
        variants = art_config.mixed_variants

    return _select_variant(bucket, variants, rng)


def _resolve_override(
    override: str, art_config: ArtConfig
) -> Optional[Tuple[str, Optional[ArtVariant]]]:
    """Validate and resolve an art_override value."""
    if override in (
        "rainbow_random",
        "rainbow_letters",
        "rainbow_halves",
        "rainbow_gradient",
        "rainbow_emoji",
        "frontier",
    ):
        return (override, None)

    for prefix, variants in [
        ("emoji_", art_config.emoji_variants),
        ("ascii_", art_config.ascii_variants),
        ("mixed_", art_config.mixed_variants),
    ]:
        if override.startswith(prefix):
            try:
                num = int(override[len(prefix):])
            except ValueError:
                return None
            if 1 <= num <= len(variants):
                return (override, variants[num - 1])
            return None

    return None


def _select_rainbow(
    config: BoardConfig, rng: random.Random
) -> Tuple[str, None]:
    """Pick a rainbow sub-mode, respecting per-variant weights."""
    if config.rainbow_per_variant_mode:
        # Per-variant weighted selection
        pool: List[Tuple[str, int]] = []
        total = 0
        for sub in RAINBOW_SUB_MODES:
            field_name = f"art_weight_rainbow_{sub}"
            field_val = getattr(config, field_name, 0)
            effective_w = config.rainbow_sub_weights.get(sub, field_val)
            pool.append((f"rainbow_{sub}", effective_w))
            total += effective_w
    else:
        # Equal weight for all 5 sub-modes
        pool = [(f"rainbow_{sub}", 1) for sub in RAINBOW_SUB_MODES]
        total = 5

    if total <= 0:
        pool = [(f"rainbow_{sub}", 1) for sub in RAINBOW_SUB_MODES]
        total = 5

    pick = rng.randrange(total)
    cum = 0
    for name, w in pool:
        cum += w
        if pick < cum:
            return (name, None)

    return ("rainbow_random", None)


def _select_variant(
    bucket: str,
    variants: List[ArtVariant],
    rng: random.Random,
) -> Tuple[str, Optional[ArtVariant]]:
    """Pick a variant from a list, using inline weights if present."""
    if not variants:
        return ("rainbow_random", None)

    has_weights = any(v.weight > 0 for v in variants)

    pool: List[Tuple[int, int]] = []
    total = 0
    for i, v in enumerate(variants):
        w = v.weight if has_weights else 1
        pool.append((i, w))
        total += w

    if total <= 0:
        # All-zero weights — equal distribution
        pool = [(i, 1) for i in range(len(variants))]
        total = len(variants)

    pick = rng.randrange(total)
    cum = 0
    for idx, w in pool:
        cum += w
        if pick < cum:
            return (f"{bucket}_{idx + 1}", variants[idx])

    return (f"{bucket}_1", variants[0])

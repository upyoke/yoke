"""Board header art surfaces. Submodules: art_config, art_select, art_render, art_progress, art_rainbow."""

# Configuration constants and dataclasses
from yoke_contracts.project_contract.board_art.config import (  # noqa: F401
    BLACK,
    CELEBRATION_EMOJIS,
    C_BLOCKED,
    C_DONE,
    C_IDEA,
    C_IMPLEMENTED,
    C_IMPLEMENTING,
    C_PLANNING,
    C_REFINED,
    C_RELEASE,
    C_REVIEWING,
    EMOJI_SETS,
    LETTER_BOUNDS,
    LETTER_MIDS,
    RAINBOW,
    RAINBOW_SUB_MODES,
    WHITE,
    ArtConfig,
    ArtVariant,
    parse_art_config,
)

# Status fill / progress
from yoke_contracts.board.art_progress import _fill_progress  # noqa: F401

# Rainbow fills
from yoke_contracts.board.art_rainbow import (  # noqa: F401
    _apply_rainbow,
    _fill_rainbow_emoji,
    _fill_rainbow_gradient,
    _fill_rainbow_halves,
    _fill_rainbow_letters,
    _fill_rainbow_random,
)

# Header rendering and stats box
from yoke_contracts.board.art_render import (  # noqa: F401
    _paste_ascii_with_stats,
    _paste_grid_with_stats,
    render_header,
)

# Stats box rendering
from yoke_contracts.board.art_stats import (  # noqa: F401
    _render_meter,
    _render_stats_box,
)

# Variant selection
from yoke_contracts.board.art_select import select_art  # noqa: F401

"""Art constants, dataclasses, and project ``.yoke/board-art`` parser.

Holds the emoji byte constants, status color palette, rainbow palette,
themed emoji sets, letter geometry, the ``ArtVariant`` and ``ArtConfig``
dataclasses, and ``parse_art_config`` plus its private collectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from yoke_contracts.project_contract.board_art.emoji import CELEBRATION_EMOJIS  # noqa: F401
from yoke_contracts.project_contract.board_art.config_paths import board_art_path_for_config

# ---------------------------------------------------------------------------
# Emoji byte constants (UTF-8)
# ---------------------------------------------------------------------------

WHITE = "⬜"  # ⬜  W-cell (fill target)
BLACK = "⬛"  # ⬛  K-cell (structural)

# Status colors  (board color palette — cool-to-warm-to-green arc)
C_DONE = "\U0001f49a"           # 💚
C_IMPLEMENTED = "\U0001f7e2"    # 🟢
C_RELEASE = "\U0001f7e9"       # 🟩
C_REVIEWING = "\U0001f7e7"     # 🟧
C_IMPLEMENTING = "\U0001f7e8"  # 🟨
C_BLOCKED = "\U0001f7e5"       # 🟥
C_REFINED = "\U0001f7e6"       # 🟦
C_PLANNING = "\U0001f7ea"      # 🟪
C_IDEA = "\U0001f7e3"          # 🟣

# Rainbow palette (6 colors)
RAINBOW = [
    "\U0001f7e5",  # 🟥
    "\U0001f7e7",  # 🟧
    "\U0001f7e8",  # 🟨
    "\U0001f7e9",  # 🟩
    "\U0001f7e6",  # 🟦
    "\U0001f7ea",  # 🟪
]

# Emoji themed sets for rainbow_emoji mode (4 sets x 6 emojis)
EMOJI_SETS: List[List[str]] = [
    # Flowers
    ["\U0001f338", "\U0001f33a", "\U0001f33b", "\U0001f337", "\U0001f339", "\U0001f33c"],
    # Fruits
    ["\U0001f34e", "\U0001f34a", "\U0001f34b", "\U0001f34f", "\U0001f351", "\U0001f347"],
    # Nature
    ["\U0001f332", "\U0001f334", "\U0001f335", "\U0001f344", "\U0001f30a", "\U0001f308"],
    # Spooky
    ["\U0001f480", "\U0001f47e", "\U0001f47b", "\U0001f383", "\U0001f36c", "\U0001f525"],
]

# Celebration emojis — canonical pool lives in board_emoji, re-exported above.

# Letter column boundaries (0-indexed emoji columns in master map)
LETTER_BOUNDS = [
    (1, 7),    # S
    (9, 15),   # U
    (17, 23),  # N
    (25, 31),  # D
    (33, 38),  # A
    (39, 45),  # Y
]
# Midpoints for halves mode (left/right split)
LETTER_MIDS = [4, 12, 20, 28, 35, 42]

# Rainbow sub-mode names (order matters for selection)
RAINBOW_SUB_MODES = ["random", "letters", "halves", "gradient", "emoji"]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ArtVariant:
    """A single parsed art variant section."""

    name: str          # e.g. "Emoji", "ASCII", "Mixed"
    lines: List[str]   # raw text lines
    weight: int        # inline weight (0 = unweighted)


@dataclass
class ArtConfig:
    """All art data parsed from project-local ``.yoke/board-art``."""

    master_map: List[str] = field(default_factory=list)
    emoji_variants: List[ArtVariant] = field(default_factory=list)
    ascii_variants: List[ArtVariant] = field(default_factory=list)
    mixed_variants: List[ArtVariant] = field(default_factory=list)
    # Optional letter column spans declared via a "# letters: a-b,c-d,..."
    # directive. Empty when undeclared; the renderer then auto-derives spans
    # from the master map (see ``derive_letter_bounds``).
    letter_bounds: List[Tuple[int, int]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Config parser
# ---------------------------------------------------------------------------


def parse_art_config(config_path: str | None, *, repo_root: str | None = None) -> ArtConfig:
    """Parse art sections from a board art file.

    ``config_path`` may point at a key=value fixture; when a sibling
    ``board-art`` file exists, that file is used. Otherwise ``repo_root``
    resolves the project-local ``.yoke/board-art``. Reads ``## Master Map``,
    ``## Emoji``, ``## ASCII``, and ``## Mixed`` sections.
    Inline ``# weight:N`` comments immediately preceding a section header
    set the variant weight. ``# weight-disabled:N`` comments are ignored.
    """
    cfg = ArtConfig()
    art_path = board_art_path_for_config(config_path, repo_root=repo_root)

    try:
        with art_path.open("r", encoding="utf-8") as fh:
            raw_lines = fh.readlines()
    except FileNotFoundError:
        return cfg

    # State machine: scan for section headers and collect content
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].rstrip("\n")

        if line.startswith("# letters:"):
            cfg.letter_bounds = _parse_letter_bounds_directive(line)
            i += 1
            continue

        if line == "## Master Map":
            i += 1
            cfg.master_map = _collect_section(raw_lines, i)
            i += len(cfg.master_map)
            continue

        if line in ("## Emoji", "## ASCII", "## Mixed"):
            section_type = line[3:]  # "Emoji", "ASCII", or "Mixed"
            # Look backward for the most recent "# weight:" comment
            weight = _find_weight_before(raw_lines, i)
            i += 1
            content = _collect_section(raw_lines, i)
            variant = ArtVariant(name=section_type, lines=content, weight=weight)
            if section_type == "Emoji":
                cfg.emoji_variants.append(variant)
            elif section_type == "ASCII":
                cfg.ascii_variants.append(variant)
            else:
                cfg.mixed_variants.append(variant)
            i += len(content)
            continue

        i += 1

    return cfg


def _collect_section(raw_lines: List[str], start: int) -> List[str]:
    """Collect content lines from *start* until the next section or blank-after-content."""
    lines: List[str] = []
    has_content = False
    i = start
    while i < len(raw_lines):
        line = raw_lines[i].rstrip("\n")
        if line.startswith("## ") or line.startswith("---"):
            break
        if not line:
            if has_content:
                break
            i += 1
            continue
        has_content = True
        lines.append(line)
        i += 1
    return lines


def _find_weight_before(raw_lines: List[str], header_idx: int) -> int:
    """Find an active ``# weight:N`` comment before the header at *header_idx*.

    Scans backward from the line immediately above the header.
    Resets on any ``## `` header boundary.
    ``# weight-disabled:`` lines are explicitly ignored.
    """
    j = header_idx - 1
    while j >= 0:
        check = raw_lines[j].rstrip("\n")
        if check.startswith("## "):
            return 0  # different section boundary
        if check.startswith("# weight-disabled:"):
            # Explicitly inactive — skip, keep scanning
            j -= 1
            continue
        if check.startswith("# weight:"):
            val_str = check[len("# weight:"):].strip()
            try:
                return int(val_str)
            except ValueError:
                return 0
        j -= 1
    return 0


# ---------------------------------------------------------------------------
# Letter geometry — declared directive, auto-derivation, resolution
# ---------------------------------------------------------------------------


def _parse_letter_bounds_directive(line: str) -> List[Tuple[int, int]]:
    """Parse a ``# letters: a-b,c-d,...`` directive into inclusive col spans.

    Malformed entries are skipped. Returns ``[]`` when nothing parses.
    """
    spec = line[len("# letters:"):].strip()
    bounds: List[Tuple[int, int]] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" not in part:
            continue
        lo_str, hi_str = part.split("-", 1)
        try:
            bounds.append((int(lo_str), int(hi_str)))
        except ValueError:
            continue
    return bounds


def derive_letter_bounds(grid_lines: List[str]) -> List[Tuple[int, int]]:
    """Infer letter column spans from a master map.

    A column is a *separator* when every cell in it is the structural
    ``BLACK`` cell; *letters* are the maximal runs of columns that contain at
    least one fill-target ``WHITE`` cell. This works for any word whose
    adjacent letters are parted by >=1 all-black column (e.g. ``EXT``). Words
    that kern two letters with no gap between them (e.g. ``YOKE``'s ``AY``)
    cannot be split this way and should declare a ``# letters:`` directive.

    Returns inclusive ``(lo, hi)`` spans, or ``[]`` when there are no WHITE
    cells.
    """
    rows = [list(line) for line in grid_lines if line.strip()]
    if not rows:
        return []
    ncols = max(len(r) for r in rows)

    def has_white(col: int) -> bool:
        return any(col < len(r) and r[col] == WHITE for r in rows)

    bounds: List[Tuple[int, int]] = []
    start: int | None = None
    for col in range(ncols):
        if has_white(col):
            if start is None:
                start = col
        elif start is not None:
            bounds.append((start, col - 1))
            start = None
    if start is not None:
        bounds.append((start, ncols - 1))
    return bounds


def resolve_letter_bounds(
    declared: List[Tuple[int, int]],
    grid_lines: List[str],
) -> List[Tuple[int, int]]:
    """Resolve the letter spans to use for letter-aware rainbow fills.

    Priority: an explicit ``# letters:`` directive (``declared``), else spans
    auto-derived from the master map, else the built-in ``LETTER_BOUNDS``
    fallback (so a missing/blank master map still renders).
    """
    if declared:
        return list(declared)
    derived = derive_letter_bounds(grid_lines) if grid_lines else []
    if len(derived) >= 2:
        return derived
    return list(LETTER_BOUNDS)

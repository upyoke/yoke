"""HC-source-glyph-contract: keep contract-breaking glyphs out of board sources.

Background
----------
macOS Terminal renders text-default emoji (the ones that require a U+FE0F
variation selector to show in emoji form) and skin-tone-modified sequences
inconsistently versus VSCode/GitHub — they collapse toward one cell, shearing
the board's emoji-grid alignment. The glyph contract
(:mod:`yoke_contracts.glyph_contract`) restricts every glyph Yoke stores or
renders to one ``Emoji_Presentation=Yes`` code point; its writers and
``HC-stored-glyph-contract`` hold stored values to it. This check holds the
literals in Yoke's own board render sources to the same contract, so a
VS16/skin-tone glyph cannot silently re-enter the render path (e.g. a
``shield`` badge added as the text-default U+1F6E1 + VS16, or a hand emoji
with a Fitzpatrick modifier).

Scope
-----
Top-level board render modules
(``packages/yoke-core/src/yoke_core/board/*.py``) plus the seeded art-column
data
(``packages/yoke-contracts/src/yoke_contracts/project_contract/board_art/data/mixed_emoji_columns.txt``)
and the baseline test-fixture project seed. The ``board/tests/`` subtree is
intentionally out of scope: test assertions legitimately name glyphs
(including ones they assert are absent).

What is flagged
---------------
Only the contract-forbidden code points that can hide inside an otherwise
ordinary literal:
  * any U+FE0F (VS16) — its preceding base is text-default, so the cluster is
    non-universal; and
  * any Fitzpatrick skin-tone modifier (U+1F3FB..U+1F3FF), standalone or
    sequenced.
Box-drawing, block elements, math symbols, and ``Emoji_Presentation=Yes`` emoji
(colored squares, circles, moons, the curated chrome set) render the same in
every surface and are NOT flagged. Shipped glyph vocabularies (status, executor,
and level glyphs) are held to the full contract by its own tests.

Posture
-------
FAIL: a violation is corrected in source by swapping the glyph for a
contract-safe one before it ships.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

from yoke_contracts.glyph_contract import SAFE_GLYPH_EXAMPLES
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)

_VS16 = 0xFE0F
_SKIN_LO, _SKIN_HI = 0x1F3FB, 0x1F3FF

# Top-level glob (no recursion) deliberately excludes ``board/tests/``.
_SCAN_DIR_GLOBS: tuple[tuple[str, str], ...] = (
    ("packages/yoke-core/src/yoke_core/board", "*.py"),
)
_SCAN_EXTRA_FILES: tuple[str, ...] = (
    (
        "packages/yoke-contracts/src/yoke_contracts/project_contract/"
        "board_art/data/mixed_emoji_columns.txt"
    ),
    # Project emoji is DB data the board renders as the `{emoji} {slug}` label;
    # the baseline test-fixture seed carries emoji literals, so guard it
    # against VS16/skin-tone re-entry too.
    "packages/yoke-core/src/yoke_core/domain/project_seed_test_helpers.py",
)

_SELF_PATH = Path(__file__).resolve()
_HC_SLUG = "HC-source-glyph-contract"
_HC_NAME = "Board source glyphs obey the glyph contract"


def _char_name(ch: str) -> str:
    try:
        return unicodedata.name(ch)
    except ValueError:
        return "?"


def _iter_scan_paths(repo_root: Path):
    for rel, glob in _SCAN_DIR_GLOBS:
        base = repo_root / rel
        if base.is_dir():
            for f in sorted(base.glob(glob)):
                if f.resolve() != _SELF_PATH:
                    yield f
    for rel in _SCAN_EXTRA_FILES:
        f = repo_root / rel
        if f.is_file():
            yield f


def scan_source_glyphs(repo_root: Path) -> list[str]:
    """Return ``path:line: detail`` strings for VS16/skin-tone glyphs.

    Exposed so tests and operators can run the same scan the HC uses.
    """
    hits: list[str] = []
    for f in _iter_scan_paths(repo_root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = f.resolve().relative_to(repo_root.resolve())
        except ValueError:
            rel = f
        for lineno, line in enumerate(text.splitlines(), start=1):
            for i, ch in enumerate(line):
                cp = ord(ch)
                if cp == _VS16:
                    base = line[i - 1] if i > 0 else ""
                    hits.append(
                        f"{rel}:{lineno}: VS16 on text-default base "
                        f"{base!r} ({_char_name(base)})"
                    )
                elif _SKIN_LO <= cp <= _SKIN_HI:
                    hits.append(
                        f"{rel}:{lineno}: skin-tone modifier {ch!r} ({_char_name(ch)})"
                    )
    return hits


def hc_source_glyph_contract(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-source-glyph-contract: VS16/skin-tone glyphs in board render sources."""
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(_HC_SLUG, _HC_NAME, "PASS", "No repo root resolved — skipping.")
        return
    hits = scan_source_glyphs(Path(repo_root_str))
    if hits:
        rec.record(
            _HC_SLUG,
            _HC_NAME,
            "FAIL",
            "Board render sources carry glyphs the glyph contract forbids "
            "(they render inconsistently in macOS Terminal):\n"
            + "\n".join(hits[:40])
            + "\nReplace each with one Emoji_Presentation glyph that needs no "
            "selector or modifier, for example " + " ".join(SAFE_GLYPH_EXAMPLES) + ".",
        )
    else:
        rec.record(_HC_SLUG, _HC_NAME, "PASS", "")


__all__ = ["hc_source_glyph_contract", "scan_source_glyphs"]

from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ("source-glyph-contract", _HC_NAME, hc_source_glyph_contract),
)

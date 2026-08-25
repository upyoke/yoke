"""Canonical executor labels, surface aliases, and their board glyphs.

Single source of truth for the executor vocabulary two surfaces have to
agree on:

* ``harness_sessions.executor`` stores a canonical harness id
  (:data:`CANONICAL_HARNESS_IDS`), and ``executor_surface`` stores
  the surface-specific alias the session actually ran on, or ``NULL``
  when no surface was known. The split is produced by
  ``yoke_core.domain.sessions_lifecycle_canonicalize.canonicalize_executor``.
* The board renders a session row with the glyph for its display name.

Both readings come from :data:`EXECUTOR_EMOJI`, so a new surface is added
in exactly one place: give it a glyph and it is simultaneously a known
label and a rendered one. Deriving the label tuples from the glyph map is
what keeps a surface from being renderable but unrecognized (or the
reverse) — the drift that lets an unknown display name look ordinary on
the board.

Lives in ``yoke-contracts`` because the board renderer lives here and the
engine core depends on this package, never the other way round.

Glyphs are restricted to ``Emoji_Presentation=Yes`` characters (no
variation selectors, no skin-tone modifiers) so board columns keep their
width in every terminal — the invariant ``HC-board-emoji-universality``
enforces over the board render sources.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Mapping, Optional, Tuple


CANONICAL_HARNESS_IDS: Tuple[str, ...] = ("claude-code", "codex", "cursor")
"""Canonical values for ``harness_sessions.executor``.

Active rows must carry one of these. Any other ``claude-*``, ``codex-*``,
or ``cursor-*`` value in that column indicates a writer that bypassed
``canonicalize_executor``.
"""

LEGACY_HARNESS_ALIASES: Mapping[str, str] = {"claude": "claude-code"}


def canonical_harness_id(executor: Optional[str]) -> str:
    """Map a canonical, legacy, or surface value to its harness family."""
    normalized = str(executor or "").strip().lower().replace("_", "-")
    if not normalized:
        raise ValueError("canonical_harness_id requires a non-empty executor")
    normalized = LEGACY_HARNESS_ALIASES.get(normalized, normalized)
    for harness_id in CANONICAL_HARNESS_IDS:
        prefix = "claude" if harness_id == "claude-code" else harness_id
        if normalized == harness_id or normalized.startswith(f"{prefix}-"):
            return harness_id
    raise ValueError(f"unknown harness executor: {executor!r}")


EXECUTOR_EMOJI: Dict[str, str] = {
    "claude-code": "\U0001f916",  # robot (coarse Claude family)
    "claude-desktop": "\U0001f34e",  # apple (desktop)
    "claude-vscode": "\U0001fa9f",  # window
    "claude-cli": "\U0001f4df",  # pager
    "codex": "\U0001f4d5",  # closed book (coarse Codex family)
    "codex-desktop": "\U0001f4bb",  # laptop
    "codex-vscode": "\U0001fa84",  # magic wand
    "codex-cli": "\U0001f4e0",  # fax
    "cursor": "\U0001f3af",  # direct hit (coarse Cursor family)
    "cursor-desktop": "\U0001f4d0",  # triangular ruler (desktop IDE surface)
    "cursor-cli": "\U0001f9ed",  # compass (terminal agent surface)
}
"""Board glyph per known executor label — the vocabulary's one listing."""


EXECUTOR_PRESENTATION: Dict[str, Mapping[str, str]] = {
    "claude": {"mark": "C", "class_name": "h-claude"},
    "codex": {"mark": "X", "class_name": "h-codex"},
    "cursor": {"mark": "C", "class_name": "h-other"},
}
"""Hosted-roster presentation stored beside the executor vocabulary."""


def executor_presentation(executor: str) -> Dict[str, str]:
    """Return definition-owned presentation with legacy family fallback."""
    normalized = str(executor or "")
    family = next(
        (
            candidate
            for candidate in EXECUTOR_PRESENTATION
            if normalized == candidate or normalized.startswith(f"{candidate}-")
        ),
        None,
    )
    presentation = EXECUTOR_PRESENTATION.get(family or "")
    if presentation is None:
        return {
            "mark": normalized[:1].upper() or "?",
            "class_name": "h-other",
        }
    return dict(presentation)


INVOCATION_CONTEXT_ORIGINATORS: FrozenSet[str] = frozenset(
    {"skill", "dash", "goal", "blitz"}
)
"""Harness-reported tokens naming how a run started, not where it runs.

Codex Desktop exports ``skill`` as the originator into subprocess env for a
skill-invoked run, so a resolver that mints whatever it finds labels one
physical surface two ways — ``codex-skill`` when the session registers from
a skill, ``codex-desktop`` when the same thread registers any other way.
Only the second is a surface, and only the second is in
:data:`EXECUTOR_EMOJI`. Every entrypoint resolver drops these tokens through
:func:`surface_alias`, so one thread resolves one
``executor_surface`` whatever path registered it.
"""


SURFACE_TOKEN_ALIASES: Mapping[str, str] = {"codex-exec": "codex-cli"}
"""Harness-reported tokens naming a surface :data:`EXECUTOR_EMOJI` already has.

``codex exec`` reports originator ``codex_exec``: the non-interactive
form of the Codex CLI, not a fourth Codex surface. Unmapped it resolves
to nothing, and one observed ``codex exec`` session stored
``executor_surface`` NULL beside every interactive Codex row's
``codex-desktop``. Minting a ``codex-exec`` label instead would give one
physical surface two names — the drift the glyph map exists to prevent.
"""


def surface_alias(candidate: Optional[str]) -> Optional[str]:
    """Return a closed-vocabulary surface alias, or ``None`` when unknown."""
    normalized = str(candidate or "").strip().lower().replace("_", "-")
    if not normalized or normalized in INVOCATION_CONTEXT_ORIGINATORS:
        return None
    normalized = SURFACE_TOKEN_ALIASES.get(normalized, normalized)
    if normalized in CANONICAL_HARNESS_IDS:
        return None
    return normalized if normalized in EXECUTOR_EMOJI else None


KNOWN_EXECUTOR_LABELS: Tuple[str, ...] = tuple(EXECUTOR_EMOJI)
"""Every value that may legitimately appear in ``executor_surface``.

``NULL`` is also legitimate (no surface-specific information was known).
Anything else is an unrecognized identity a writer invented rather than
resolved.
"""


KNOWN_SURFACE_LABELS: Tuple[str, ...] = tuple(
    label for label in EXECUTOR_EMOJI if label not in CANONICAL_HARNESS_IDS
)
"""The surface-specific subset: aliases that belong only in the display column."""


__all__ = [
    "CANONICAL_HARNESS_IDS",
    "EXECUTOR_EMOJI",
    "EXECUTOR_PRESENTATION",
    "INVOCATION_CONTEXT_ORIGINATORS",
    "LEGACY_HARNESS_ALIASES",
    "KNOWN_EXECUTOR_LABELS",
    "KNOWN_SURFACE_LABELS",
    "SURFACE_TOKEN_ALIASES",
    "canonical_harness_id",
    "executor_presentation",
    "surface_alias",
]

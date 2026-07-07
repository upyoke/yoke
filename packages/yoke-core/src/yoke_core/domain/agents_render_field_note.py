"""Marker expansion for the field-note footer in canonical agent bodies.

Canonical agent prompts (``runtime/agents/<role>.md``) carry a single-line
field-note marker::

    <!-- YOKE:FIELD-NOTE -->

The renderer pipeline (:mod:`yoke_core.domain.agents_render_subagent_hooks`
and :mod:`yoke_core.domain.agents_render_codex`) calls
:func:`expand_field_note_markers` on the canonical body before wrapping
it for the Claude or Codex adapter. The single-line marker is replaced by
:data:`yoke_contracts.field_note_text.FOOTER` rendered as a
markdown block — three lines: directive, copy-paste recipe, ``--help``
pointer. The marker itself is consumed by the replacement (unlike the
paired ``YOKE:DB-PACKET`` markers); canonical body remains the single
source of truth on disk.

Drift discipline mirrors :mod:`agents_render_context`:

* :func:`detect_field_note_marker_drift` flags hand-authored copies
  of the canonical directive language sitting alongside the marker —
  the same shape as the ``DB-PACKET`` stale-term regression. Surfaced by
  ``HC-harness-substrate-drift`` via :func:`detect_substrate_drift`.
"""

from __future__ import annotations

import re

from yoke_contracts.field_note_text import (
    BASIC_RECIPE,
    DIRECTIVE,
    FOOTER,
    HELP_POINTER,
)


MARKER: str = "<!-- YOKE:FIELD-NOTE -->"

# Match the marker preceded by optional leading whitespace and followed
# optionally by a trailing newline so the replacement leaves clean line
# boundaries when the canonical body places the marker on its own line.
_MARKER_LINE_RE = re.compile(
    r"(?P<indent>[ \t]*)" + re.escape(MARKER) + r"(?P<trailing>\n?)"
)


def expand_field_note_markers(text: str) -> str:
    """Replace every ``<!-- YOKE:FIELD-NOTE -->`` marker with FOOTER.

    The marker is single-line: the entire matched line (indent + marker +
    optional trailing newline) is replaced by ``FOOTER`` followed by a
    newline so the inserted block keeps the surrounding paragraph shape.

    Returns *text* unchanged when no marker is present. Calling
    :func:`expand_field_note_markers` on already-expanded text is a
    no-op (no marker remains to expand), giving stable repeat-render
    output.
    """
    if MARKER not in text:
        return text
    return _MARKER_LINE_RE.sub(lambda _m: f"{FOOTER}\n", text)


def count_field_note_markers(text: str) -> int:
    """Return the number of ``YOKE:FIELD-NOTE`` markers in *text*."""
    return len(_MARKER_LINE_RE.findall(text))


def detect_field_note_marker_drift(text: str, source_label: str) -> list[str]:
    """Return drift descriptions for one canonical body's field-note marker.

    Two regression layers:

    1. **Multiple-marker drift.** A canonical body must carry at most one
       marker — the renderer expands every occurrence, so duplicates would
       multi-render the footer.
    2. **Hand-authored copy alongside marker.** When the marker is present
       and any line from the canonical FOOTER text (``DIRECTIVE``,
       ``BASIC_RECIPE``, or ``HELP_POINTER``) also appears in the
       canonical body outside the marker line, the body has a stale copy
       shadowing the generated footer.

    Empty list means no drift. Returned strings carry a stable prefix so
    ``HC-harness-substrate-drift`` can render them grouped by source.
    """
    drift: list[str] = []
    marker_count = count_field_note_markers(text)
    if marker_count > 1:
        drift.append(
            f"field-note: {source_label}: {marker_count} markers; "
            "expected at most one"
        )
    if marker_count >= 1:
        for stale in (DIRECTIVE, BASIC_RECIPE, HELP_POINTER):
            if stale in text:
                drift.append(
                    f"field-note: {source_label}: hand-authored copy "
                    f"of canonical FOOTER line alongside marker"
                )
                break
    return drift


__all__ = (
    "MARKER",
    "expand_field_note_markers",
    "count_field_note_markers",
    "detect_field_note_marker_drift",
)

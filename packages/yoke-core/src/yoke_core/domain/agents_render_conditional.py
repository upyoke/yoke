"""Harness-conditional rendering for canonical agent prompts.

Canonical agent prompts (``runtime/agents/<role>.md``) may carry
harness-conditional markers of the form::

    <!-- YOKE:HARNESS claude start -->
    ... Claude-only prose ...
    <!-- YOKE:HARNESS end -->

The renderer (:mod:`yoke_core.domain.agents_render` for Claude,
:mod:`yoke_core.domain.agents_render_codex` for Codex) calls
:func:`apply_conditional_blocks` on the canonical body before wrapping
it for each harness adapter. Sections whose declared harness id matches
the target harness are emitted with the marker comments stripped.
Sections with any other harness id are removed entirely along with
their markers.

This is the structural fix for the asymmetric-truth-rendering gap:
Claude-only primitives (``Monitor``, ``Bash(run_in_background)``,
``ScheduleWakeup``, ``TaskOutput``, ``TaskStop``, ``PreToolUse``)
are fenced in ``claude`` blocks so the Codex adapter never inherits
prose teaching primitives that do not exist in its harness.
"""

from __future__ import annotations

import re


# Canonical harness ids. Adding a harness extends this surface; call sites
# import these names instead of duplicating literal strings.
CLAUDE_HARNESS_ID = "claude"
CODEX_HARNESS_ID = "codex"
HARNESS_IDS: frozenset[str] = frozenset({CLAUDE_HARNESS_ID, CODEX_HARNESS_ID})


# Match either a *block-level* marker (alone on its line: leading
# whitespace before, only the trailing newline after) or an *inline*
# marker (other content on the same line). The alternation keeps the
# behaviour explicit per shape:
#   * block-level matches consume the entire line including its newline,
#     so dropping the block leaves a clean line break between paragraphs;
#   * inline matches consume only the marker tag, preserving the
#     surrounding whitespace that the author intended.
MARKER_START_RE = re.compile(
    r"(?:(?<=\n)|\A)[ \t]*<!-- YOKE:HARNESS ([\w-]+) start -->[ \t]*\n"
    r"|<!-- YOKE:HARNESS ([\w-]+) start -->"
)
MARKER_END_RE = re.compile(
    r"(?:(?<=\n)|\A)[ \t]*<!-- YOKE:HARNESS end -->[ \t]*\n"
    r"|<!-- YOKE:HARNESS end -->"
)


class MarkerSyntaxError(ValueError):
    """Raised when canonical text contains a malformed conditional marker."""


def _scan_tokens(text: str) -> list[tuple[str, re.Match[str]]]:
    """Return ordered tokens for every YOKE:HARNESS marker in *text*.

    Each token is ``(kind, match)`` where ``kind`` is ``"start"`` or
    ``"end"`` and ``match`` is the matched regex object. Tokens are
    sorted by their start offset, so consumers walk them in source order.
    """
    tokens: list[tuple[str, re.Match[str]]] = []
    for m in MARKER_START_RE.finditer(text):
        tokens.append(("start", m))
    for m in MARKER_END_RE.finditer(text):
        tokens.append(("end", m))
    # Sort by start offset, then prefer the longer match at the same offset
    # so block-level alternative (which extends to the trailing newline)
    # wins over the inline alternative when both match.
    tokens.sort(key=lambda t: (t[1].start(), -(t[1].end() - t[1].start())))
    return tokens


def _line_for_offset(text: str, offset: int) -> int:
    """Return the 1-based line number containing *offset*."""
    return text.count("\n", 0, offset) + 1


def find_conditional_pairs(text: str) -> list[dict]:
    """Return one entry per matched ``start`` / ``end`` pair in *text*.

    Each entry is a dict with keys ``harness``, ``block_start`` (offset
    of the first character consumed by the start marker), ``block_end``
    (offset just past the last character consumed by the end marker),
    ``inner_start`` (offset just past the start marker), and
    ``inner_end`` (offset of the start of the end marker — i.e., where
    the block's inner content stops).

    Raises :class:`MarkerSyntaxError` for nested blocks, unmatched
    start markers, unmatched end markers, or unknown harness ids.
    """
    tokens = _scan_tokens(text)
    pairs: list[dict] = []
    stack: list[re.Match[str]] = []
    for kind, m in tokens:
        if kind == "start":
            if stack:
                raise MarkerSyntaxError(
                    f"nested YOKE:HARNESS start at line "
                    f"{_line_for_offset(text, m.start())}, "
                    f"offset {m.start()}: "
                    f"already inside a block opened at offset "
                    f"{stack[-1].start()}"
                )
            # group(1) is the block-level alternative, group(2) is inline.
            harness = m.group(1) or m.group(2)
            if harness not in HARNESS_IDS:
                raise MarkerSyntaxError(
                    f"unknown harness id at line "
                    f"{_line_for_offset(text, m.start())}, "
                    f"offset {m.start()}: "
                    f"{harness!r} (known: {sorted(HARNESS_IDS)})"
                )
            stack.append(m)
        else:  # "end"
            if not stack:
                raise MarkerSyntaxError(
                    f"unmatched YOKE:HARNESS end at line "
                    f"{_line_for_offset(text, m.start())}, "
                    f"offset {m.start()}"
                )
            start_m = stack.pop()
            pairs.append(
                {
                    "harness": start_m.group(1) or start_m.group(2),
                    "block_start": start_m.start(),
                    "block_end": m.end(),
                    "inner_start": start_m.end(),
                    "inner_end": m.start(),
                }
            )
    if stack:
        m = stack[-1]
        harness = m.group(1) or m.group(2)
        raise MarkerSyntaxError(
            f"unmatched YOKE:HARNESS start at line "
            f"{_line_for_offset(text, m.start())}, offset {m.start()}: "
            f"harness={harness!r}"
        )
    return pairs


def validate_conditional_marker_syntax(text: str) -> list[str]:
    """Return human-readable issues for malformed conditional markers.

    Empty list means every start marker has a matching end marker, no
    blocks are nested, and every harness id is in :data:`HARNESS_IDS`.
    The renderer ``check`` command surfaces this list when present.
    """
    try:
        find_conditional_pairs(text)
    except MarkerSyntaxError as exc:
        return [str(exc)]
    return []


def apply_conditional_blocks(text: str, target_harness: str) -> str:
    """Drop wrong-harness blocks and strip markers from matching blocks.

    Sections whose declared harness id equals *target_harness* are kept
    with their marker comments removed. Sections with any other harness
    id are removed entirely.

    Idempotent: text containing no markers is returned unchanged; text
    that has already been processed (and therefore has no remaining
    markers) is returned unchanged.

    Raises :class:`MarkerSyntaxError` for malformed markers and
    :class:`ValueError` for an unknown ``target_harness``.
    """
    if target_harness not in HARNESS_IDS:
        raise ValueError(
            f"unknown target harness {target_harness!r} "
            f"(known: {sorted(HARNESS_IDS)})"
        )
    pairs = find_conditional_pairs(text)
    if not pairs:
        return text
    out: list[str] = []
    cursor = 0
    for p in pairs:
        out.append(text[cursor : p["block_start"]])
        if p["harness"] == target_harness:
            out.append(text[p["inner_start"] : p["inner_end"]])
        cursor = p["block_end"]
    out.append(text[cursor:])
    return "".join(out)


def detect_conditional_marker_drift(text: str, source_label: str) -> list[str]:
    """Return drift descriptions for one canonical body's conditional markers.

    Empty list means every start marker has a matching end marker, no
    blocks are nested, and every harness id is recognised. Non-empty
    entries are formatted as ``"conditional-marker: <source>: <issue>"``
    for the lane R / task 10 health check ``HC-harness-substrate-drift``.
    """
    return [
        f"conditional-marker: {source_label}: {issue}"
        for issue in validate_conditional_marker_syntax(text)
    ]

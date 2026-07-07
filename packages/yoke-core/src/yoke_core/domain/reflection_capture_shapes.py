"""Multi-shape reflection block orchestrator with structured CaptureResult.

Sibling to :mod:`yoke_core.domain.reflection_capture`. Holds the
top-level :func:`parse_text` orchestrator and the :class:`CaptureResult`
the PostToolUse hook reports through ``ReflectionCaptureHookFired`` /
``ReflectionCaptureHookUnhandled`` events. The per-shape entry parsers
live in :mod:`yoke_core.domain.reflection_capture_shape_parsers` so
this file stays comfortably under the 350-line authored-file cap.

Catalogues the recognized entry shapes plus the false-positive patterns;
this module is the authoritative production parser the hook reads from.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from yoke_core.domain.reflection_capture_freeform import collect_shape_a_errors
from yoke_core.domain.reflection_capture_shape_parsers import (
    ReflectionEntry,
    get_shape_parsers_in_priority,
)


_CANONICAL_FRAMING_RE = re.compile(r"---BEGIN ENTRY---")


_REFLECTION_START_RE = re.compile(r"---REFLECTION-START---")
_REFLECTION_END_RE = re.compile(r"---REFLECTIONS?-END---")
_CODE_FENCE_BACKTICKS_RE = re.compile(r"`[^`\n]*REFLECTION-START[^`\n]*`")
_LINE_NUMBER_PREFIX_RE = re.compile(r"^\s*\d+\s*[→\t]", re.MULTILINE)
_EMPTY_REFLECTION_HEADING_RE = re.compile(
    r"^##\s+Reflection\s*\n+\s*(?:\(no entries\)|$|##)",
    re.MULTILINE,
)
_NO_REFLECTION_LITERAL_RE = re.compile(
    r"^\s*no[\s-]reflection\s*$"
    r"|^\s*\(no\s+\w+\)\s*$"
    r"|^\s*no\s+\w+\s*\.?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BARE_END_MARKERS_ONLY_RE = re.compile(
    r"^(?:\s*---END ENTRY---\s*)+$",
    re.MULTILINE | re.DOTALL,
)
# Template/placeholder content: BEGIN/END framing wrapping a bracketed
# placeholder like ``[learning entry]``, OR lines composed entirely of
# ``[name] | [name] | ...`` template-style bracket tokens.
_BRACKET_PLACEHOLDER_RE = re.compile(
    r"^(?:\s*---BEGIN ENTRY---\s*\n)?\s*\[[^\]\n]+\](?:\s*\n\s*---END ENTRY---\s*)?\s*$",
    re.DOTALL,
)
_BRACKET_TOKEN_LINE_RE = re.compile(
    r"^\s*\[[^\]\n]+\](?:\s*\|\s*\[[^\]\n]+\])+\s*$",
    re.MULTILINE,
)


@dataclass
class CaptureResult:
    """Structured capture result.

    Carries the nine structured counts alongside the
    legacy field names (``entries_parsed``, ``entries_skipped``,
    ``errors``) the existing CLI summary in
    :mod:`yoke_core.domain.reflection_capture` prints. The legacy
    fields are concrete attributes (not properties) so callers that
    instantiate ``CaptureResult(entries_parsed=N, ...)`` continue to work.
    """
    blocks_seen: int = 0
    blocks_parsed_successfully: int = 0
    blocks_skipped_known_falsepositive: int = 0
    blocks_unrecognized: int = 0
    blocks_partial_no_end_marker: int = 0
    entries_persisted: int = 0
    entries_duplicate_skipped: int = 0
    entries_persist_failed: int = 0
    unrecognized_block_examples: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    # Legacy field names (kept for the CLI summary and prior persist_entries
    # callers). ``entries_parsed`` is the total entries the parse pass
    # extracted; ``entries_skipped`` is the duplicate-on-insert count
    # (aliased by ``entries_duplicate_skipped`` in the structured set).
    entries_parsed: int = 0
    entries_skipped: int = 0


def _looks_like_read_tool_output(block_text: str) -> bool:
    """Block content carries the ``<lineno>→`` prefix the Read tool emits."""
    matches = _LINE_NUMBER_PREFIX_RE.findall(block_text)
    return len(matches) >= 2


def _looks_like_code_fence_documentation(window_around_start: str) -> bool:
    """Block is wrapped in backticks (inline code fence prose)."""
    return bool(_CODE_FENCE_BACKTICKS_RE.search(window_around_start))


_SHAPE_A_INNER_RE = re.compile(
    r"---BEGIN ENTRY---\s*\n(.*?)\n\s*---END ENTRY---", re.DOTALL,
)
_TEMPLATE_FIELD_VALUE_RE = re.compile(r":\s*\{[^}]+\}\s*$")
_ELLIPSIS_BODY_RE = re.compile(r"^\.{2,}$")


def _looks_like_canonical_documentation_template(block_text: str) -> bool:
    """Canonical-framed block whose entry body is literal ``...`` or all ``{template}`` values."""
    for raw in _SHAPE_A_INNER_RE.findall(block_text):
        non_blank = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        if not non_blank:
            continue
        if all(_ELLIPSIS_BODY_RE.match(ln) for ln in non_blank):
            return True
        if all(_TEMPLATE_FIELD_VALUE_RE.search(ln) for ln in non_blank):
            return True
    return False


def _classify_block(
    block_text: str, block_window: str, default_agent: str,
) -> Tuple[str, Optional[List[ReflectionEntry]], Optional[str]]:
    """Return ``(classification, entries, fp_kind)`` for one block.

    ``classification`` is one of ``parsed``, ``false_positive``,
    ``unrecognized``. ``fp_kind`` names the specific false-positive when
    classification is ``false_positive``.
    """
    if _looks_like_code_fence_documentation(block_window):
        return ("false_positive", None, "code_fence_documentation")
    if _looks_like_read_tool_output(block_text):
        return ("false_positive", None, "read_tool_line_prefix")
    stripped = block_text.strip()
    if not stripped:
        return ("false_positive", None, "empty_block")
    if _NO_REFLECTION_LITERAL_RE.search(stripped):
        return ("false_positive", None, "no_reflection_literal")
    if _BARE_END_MARKERS_ONLY_RE.fullmatch(stripped):
        return ("false_positive", None, "bare_end_marker_only")
    if _BRACKET_PLACEHOLDER_RE.fullmatch(stripped):
        return ("false_positive", None, "bracket_placeholder")
    # Block where every non-empty line is a bracket-token template line.
    nonempty_lines = [ln for ln in stripped.split("\n") if ln.strip()]
    if nonempty_lines and all(
        _BRACKET_TOKEN_LINE_RE.fullmatch(ln) for ln in nonempty_lines
    ):
        return ("false_positive", None, "bracket_token_template")
    if _looks_like_canonical_documentation_template(block_text):
        return ("false_positive", None, "canonical_documentation_template")

    for shape_fn in get_shape_parsers_in_priority():
        entries = shape_fn(block_text, default_agent)
        if entries:
            return ("parsed", entries, None)
    return ("unrecognized", None, None)


def _block_errors(block_text: str) -> list[str]:
    """Per-block error strings: malformed canonical entries only.

    Freeform blocks with end markers but no parseable category heads
    are absorbed by ``try_shape_generic_freeform`` as ``freeform``
    entries rather than raising an error; the canonical-template hint
    is no longer surfaced because the content is now captured.
    """
    errors: list[str] = []
    if _CANONICAL_FRAMING_RE.search(block_text):
        errors.extend(collect_shape_a_errors(block_text))
    return errors


def parse_text(
    text: str, *, default_agent: str = "unknown",
) -> Tuple[List[ReflectionEntry], CaptureResult]:
    """Scan ``text``, classify every reflection-bounded block, return entries + result.

    The returned :class:`CaptureResult` carries the structured counts;
    entries are returned separately so the caller can persist
    them and fill in ``entries_persisted`` / ``entries_duplicate_skipped``
    / ``entries_persist_failed`` afterwards.
    """
    result = CaptureResult()
    entries: list[ReflectionEntry] = []

    if "REFLECTION-START" not in text and "REFLECTION-END" not in text:
        return entries, result

    if _EMPTY_REFLECTION_HEADING_RE.search(text):
        result.blocks_skipped_known_falsepositive += 1
        return entries, result

    starts = list(_REFLECTION_START_RE.finditer(text))
    ends = list(_REFLECTION_END_RE.finditer(text))

    for i, start_match in enumerate(starts):
        result.blocks_seen += 1
        s = start_match.start()
        window_around = text[
            max(0, s - 2): min(len(text), s + len("---REFLECTION-START---") + 2)
        ]
        # Find the next end marker after this start (if any).
        end_match = next(
            (e for e in ends if e.start() > start_match.end()), None,
        )
        recovered_from_missing_end = False
        if end_match is None:
            # Recovery: some agents close blocks with only `---END ENTRY---`
            # (the inner marker) instead of the canonical `---REFLECTION-END---`
            # outer envelope. Treat the next `---REFLECTION-START---` (or
            # end-of-text) as the implicit envelope boundary so the content
            # is not silently lost. A trailing dangling `---END ENTRY---` on
            # the block is trimmed so it does not confuse shape parsers.
            next_start = starts[i + 1] if i + 1 < len(starts) else None
            end_offset = next_start.start() if next_start else len(text)
            block_text = text[start_match.end(): end_offset].strip("\n")
            block_text = re.sub(
                r"\n\s*---END ENTRY---\s*$", "", block_text,
            )
            recovered_from_missing_end = True
        else:
            block_text = text[start_match.end(): end_match.start()].strip("\n")

        classification, parsed_entries, _fp_kind = _classify_block(
            block_text, window_around, default_agent,
        )
        # Block lacked a proper outer end marker but its content classified
        # to something — count it as parsed (or fp) per the classification,
        # and only count it as partial_no_end_marker when content is still
        # unrecognized after recovery. This preserves the telemetry signal
        # while no longer dropping recoverable content.
        if recovered_from_missing_end and classification == "unrecognized":
            result.blocks_partial_no_end_marker += 1
            continue
        # FP blocks (bracket placeholders, canonical doc templates, etc.)
        # carry canonical framing but no real content — surfacing a
        # missing-category error would mis-describe a known template.
        if classification != "false_positive":
            result.errors.extend(_block_errors(block_text))
        if classification == "parsed":
            assert parsed_entries is not None
            result.blocks_parsed_successfully += 1
            entries.extend(parsed_entries)
        elif classification == "false_positive":
            result.blocks_skipped_known_falsepositive += 1
        else:
            result.blocks_unrecognized += 1
            excerpt = block_text[:400]
            result.unrecognized_block_examples.append({
                "excerpt": excerpt,
                "classification_attempt": "unrecognized_shape",
            })

    return entries, result


__all__ = [
    "CaptureResult",
    "ReflectionEntry",
    "parse_text",
]

"""Section extractor + heading helpers for the rendered item body.

Sibling of :mod:`render_body`. Owns:

* :func:`extract_section` — given a rendered body string and a section
  heading, return the section's content (everything between the
  heading line and the next ``## `` heading at the top level). Pure,
  line-oriented; honors fenced code blocks (``` / ~~~).
* :func:`strip_duplicate_heading`, :func:`strip_spec_h1`,
  :func:`render_section_block`, :func:`section_has_content` — small
  heading-trim helpers used by the parent body renderer. Lifted here
  from :mod:`render_body` so the parent stays under the 350-line
  authored-file cap when the ``--section`` mode wires in.

Public API surface kept tight: agents reach for the CLI wiring
(``items get YOK-N body --section "## File Budget"``), which calls
:func:`extract_section` through :mod:`render_body.render_section`.
"""

from __future__ import annotations

from typing import Optional

__all__ = [
    "RENDERER_OWNED_BODY_HEADINGS",
    "extract_section",
    "has_top_level_section",
    "normalise_heading",
    "replace_section",
    "section_has_content",
    "strip_duplicate_heading",
    "strip_renderer_owned_section",
    "strip_renderer_owned_sections",
    "strip_spec_h1",
    "render_section_block",
]


# Renderer-owned body sections. The DB-backed body renderer authors
# these from authoritative state; an operator-authored copy in spec
# (or any structured field) is silently stripped so the body shows
# one canonical version, not two.
RENDERER_OWNED_BODY_HEADINGS = (
    "## Path Claims",
    "## DB Claim",
    "## Architecture Impact",
)


_HEADING_PREFIX = "## "


def section_has_content(value: Optional[str]) -> bool:
    return value is not None and value != ""


def strip_duplicate_heading(content: str, heading: str) -> str:
    """Drop a leading ``heading`` line from ``content`` if it duplicates."""
    lines = content.splitlines()
    if not lines:
        return content
    if lines[0].rstrip() != heading.rstrip():
        return content
    lines = lines[1:]
    while lines and lines[0].strip() == "":
        lines = lines[1:]
    return "\n".join(lines)


def strip_spec_h1(content: str) -> str:
    """Drop a leading ``# `` line (spec H1 sits in the rendered heading)."""
    lines = content.splitlines()
    if not lines:
        return content
    if not lines[0].startswith("# "):
        return content
    lines = lines[1:]
    while lines and lines[0].strip() == "":
        lines = lines[1:]
    return "\n".join(lines)


def render_section_block(heading: str, content: str) -> str:
    """Render a top-level section as ``heading`` + ``content`` (trimmed)."""
    trimmed = content.rstrip("\n")
    if trimmed:
        return f"{heading}\n\n{trimmed}"
    return heading


def strip_renderer_owned_section(content: str, heading: str) -> str:
    """Remove a top-level ``## <heading>`` block from operator-authored content.

    Some body sections — ``## Path Claims``, ``## DB Claim``,
    ``## Architecture Impact``, ``## Blocked`` — are emitted from
    authoritative DB state by the body renderer. When an operator-
    authored field (spec, design_spec, etc.) also contains one of
    those headings as planning prose, the rendered body shows the
    section twice. This helper drops the operator-authored copy so
    the DB-backed renderer remains the only source of truth.

    Strips the heading line and every following line up to (but not
    including) the next top-level ``## `` line or end-of-content.
    Honors code fences identically to :func:`extract_section`. Returns
    ``content`` unchanged when the heading is not present.
    """
    if not content:
        return content
    target = normalise_heading(heading)
    if not target:
        return content
    target_line = f"{_HEADING_PREFIX}{target}"

    lines = content.splitlines()
    kept: list[str] = []
    skipping = False
    in_fence = False
    stripped_any = False
    for line in lines:
        stripped = line.strip()
        if not skipping:
            if not in_fence and line.rstrip() == target_line:
                skipping = True
                stripped_any = True
                continue
            if _is_fence(stripped):
                in_fence = not in_fence
            kept.append(line)
            continue
        if _is_fence(stripped):
            in_fence = not in_fence
            continue
        if (
            not in_fence
            and line.startswith(_HEADING_PREFIX)
            and not line.startswith("### ")
            and not line.startswith("#### ")
        ):
            skipping = False
            kept.append(line)
            continue
    if not stripped_any:
        return content
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


def strip_renderer_owned_sections(content: str, headings: tuple) -> str:
    """Apply :func:`strip_renderer_owned_section` for each heading."""
    for heading in headings:
        content = strip_renderer_owned_section(content, heading)
    return content


def normalise_heading(raw: str) -> str:
    """Strip surrounding whitespace and a leading ``## `` from ``raw``.

    Callers may pass the heading either as ``"## File Budget"`` or
    just ``"File Budget"``. The extractor matches on the canonical
    ``"## "``-led form, so we strip the prefix once on input.
    """
    value = raw.strip()
    if value.startswith(_HEADING_PREFIX):
        value = value[len(_HEADING_PREFIX):].strip()
    elif value.startswith("##"):
        value = value[2:].strip()
    return value


def _is_fence(stripped: str) -> bool:
    """Return True iff ``stripped`` opens or closes a fenced code block."""
    if stripped.startswith("```"):
        return True
    if stripped.startswith("~~~"):
        return True
    return False


def extract_section(body: str, heading: str) -> Optional[str]:
    """Return the content between ``## <heading>`` and the next ``## `` line.

    ``heading`` accepts ``"## File Budget"`` or ``"File Budget"``;
    both normalise to the same match. Match is case-sensitive on
    the canonical ``## <name>`` form.

    Returns ``None`` when the heading is not present. Returns an
    empty string when the heading is present but the section has
    no content before the next sibling heading or end-of-body.

    Markdown code fences (``` / ~~~) suspend section-boundary
    detection — a ``## `` line inside a fenced block does not end
    the section. Nested ``### `` / ``#### `` headings stay inside
    the section content. The returned content has leading and
    trailing blank lines stripped.
    """
    if not body:
        return None
    target = normalise_heading(heading)
    if not target:
        return None
    target_line = f"{_HEADING_PREFIX}{target}"

    lines = body.splitlines()
    inside = False
    in_fence = False
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not inside:
            if line.rstrip() == target_line:
                inside = True
                continue
            continue
        # Inside the target section. Track code fences so a
        # ``## `` line inside a fenced block stays as content.
        if _is_fence(stripped):
            in_fence = not in_fence
            collected.append(line)
            continue
        if (
            not in_fence
            and line.startswith(_HEADING_PREFIX)
            and not line.startswith("### ")
            and not line.startswith("#### ")
        ):
            # Next top-level ``## `` heading — end of section.
            break
        collected.append(line)

    if not inside:
        return None

    # Strip leading and trailing blank lines.
    while collected and not collected[0].strip():
        collected.pop(0)
    while collected and not collected[-1].strip():
        collected.pop()
    return "\n".join(collected)


def _find_top_level_heading_index(
    lines: list, target_line: str,
) -> Optional[int]:
    """Return the line index of the first non-fenced match of *target_line*."""
    in_fence = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not in_fence and line.rstrip() == target_line:
            return i
        if _is_fence(stripped):
            in_fence = not in_fence
    return None


def has_top_level_section(content: str, heading: str) -> bool:
    """Return True iff ``## heading`` is present at the top level.

    Fence-aware companion to :func:`extract_section`: a ``## `` line
    inside a fenced code block does not count as a match. Use this
    instead of ``extract_section(...) is not None`` when callers must
    agree with :func:`replace_section` about what "top-level" means.
    """
    if not content:
        return False
    target = normalise_heading(heading)
    if not target:
        return False
    return _find_top_level_heading_index(
        content.splitlines(keepends=True), f"{_HEADING_PREFIX}{target}",
    ) is not None


def replace_section(
    content: str, heading: str, new_section_content: str,
) -> Optional[str]:
    """Replace the body of a top-level ``## heading`` block in ``content``.

    Returns ``None`` when ``heading`` is not present at the top level
    (mirrors :func:`extract_section`'s "not found" signal). Returns the
    updated ``content`` otherwise.

    Boundary detection honors fenced code blocks: a ``## `` line inside a
    ``````` or ``~~~`` block is ignored both when locating
    the heading and when finding the next sibling section. Bytes before
    the matched heading line and from the next sibling ``## `` heading
    (or end of input) onward are preserved verbatim; only the section's
    own block is rewritten.

    The new section is emitted as ``## <heading>\\n\\n<new content>``
    with the new content's trailing newlines trimmed. A blank-line
    separator is appended before the next sibling section. When the
    replaced section is the last one in the field, the input's trailing
    newline behavior is preserved.
    """
    if not content:
        return None
    target = normalise_heading(heading)
    if not target:
        return None
    target_line = f"{_HEADING_PREFIX}{target}"

    lines = content.splitlines(keepends=True)
    start_idx = _find_top_level_heading_index(lines, target_line)
    if start_idx is None:
        return None

    # Recompute in_fence at start_idx so end-finding tracks fences from there.
    in_fence = False
    for line in lines[:start_idx]:
        if _is_fence(line.strip()):
            in_fence = not in_fence

    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        stripped = lines[j].strip()
        if _is_fence(stripped):
            in_fence = not in_fence
            continue
        if (
            not in_fence
            and lines[j].startswith(_HEADING_PREFIX)
            and not lines[j].startswith("### ")
            and not lines[j].startswith("#### ")
        ):
            end_idx = j
            break

    trimmed_new = (new_section_content or "").rstrip("\n")
    if trimmed_new:
        replacement = f"{target_line}\n\n{trimmed_new}\n"
    else:
        replacement = f"{target_line}\n"

    if end_idx < len(lines):
        if not replacement.endswith("\n\n"):
            replacement += "\n"
    else:
        if content.endswith("\n"):
            if not replacement.endswith("\n"):
                replacement += "\n"
        else:
            replacement = replacement.rstrip("\n")

    return (
        "".join(lines[:start_idx])
        + replacement
        + "".join(lines[end_idx:])
    )

"""Parser helpers for ``master_plan_check``.

This module is the parser leg of the parser/evaluator/reporter triplet
that backs ``yoke_core.domain.master_plan_check``. It owns:

- ``parse_frontier_entries`` — extract numbered entries from the
  ``## ... Backlog By Generation`` > ``#### Remaining frontier`` /
  ``#### Landed`` subsections.
- ``parse_prerequisite_prose`` — extract prerequisite/enabling
  relationships from plan prose ("depends on", "must not outrun",
  etc.).

Both parsers are intentionally lenient and emit advisories rather than
raising on malformed input. Parsed shapes (``FrontierEntry``,
``ProseRelationship``) are owned by the entry-point module because they
also flow through evaluator and reporter; this module imports them via
deferred local imports inside functions to avoid a circular import.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from yoke_core.domain.master_plan_check import (
        FrontierEntry,
        ProseRelationship,
    )


# Keywords that identify a "B is a prerequisite for A" relationship in
# prose. Order matters: longer keywords are listed first so short
# substrings do not shadow the longer variants during matching.
_PREREQ_KEYWORDS: Tuple[str, ...] = (
    "must not outrun",
    "prerequisite slice",
    "prerequisite slices",
    "prerequisite for",
    "prerequisite",
    "depends on",
    "must come before",
    "builds on",
    "built on",
    "blocks",
    "blocked by",
    "precondition for",
    "precondition",
    "requires",
)


# Public item-ref regex (``PREFIX-N``). Allow optional backticks and
# leading zeros; the prefix follows the projects.public_item_prefix
# shape (a capital letter then capitals/digits), so plans for any
# project parse with their own refs (YOK-N, EXT-N, ...).
_PUBLIC_ITEM_REF_RE = re.compile(r"`?([A-Z][A-Z0-9]*)-0*(\d+)`?")


_NUMBERED_ENTRY_RE = re.compile(r"^\s{0,3}(\d+)[.)]\s+(.*)$")
_PHASE_BULLET_RE = re.compile(r"^\s{0,3}[-*]\s+Phase\s+\d+\b.*$")


def _yok_ids_in(text: str) -> List[str]:
    """Return canonical ``PREFIX-N`` ids mentioned in *text*, in order."""
    seen: List[str] = []
    for match in _PUBLIC_ITEM_REF_RE.finditer(text):
        yok_id = f"{match.group(1)}-{int(match.group(2))}"
        if yok_id not in seen:
            seen.append(yok_id)
    return seen


def _strip_title(entry_text: str, yok_id: str) -> str:
    """Best-effort extraction of a human title from an entry line.

    Handles both prevalent MASTER-PLAN.md shapes:

    - Landed:   ``N. — `Define the /yoke do ...```
    - Remaining: ``N. `Add /yoke feed ...```
    """
    # Drop the PREFIX-N ref (with optional backticks, parens, em-dash)
    # so whatever remains is the title fragment.
    text = entry_text
    prefix, _, bare = yok_id.rpartition("-")
    # Remove bracketed / parenthetical forms: or
    text = re.sub(rf"\(`?{re.escape(prefix)}-0*{bare}`?\)", "", text)
    # Remove inline refs with optional backticks
    text = re.sub(rf"`?{re.escape(prefix)}-0*{bare}`?", "", text)
    # Common separators between id and title
    text = text.strip()
    text = re.sub(r"^[\-—–:\s]+", "", text)
    text = re.sub(r"[\-—–:\s]+$", "", text)
    # Strip wrapping backticks
    text = text.strip("`").strip()
    return text


def parse_frontier_entries(
    md_text: str,
) -> Tuple[List["FrontierEntry"], List["FrontierEntry"], List[str]]:
    """Parse MASTER-PLAN.md and return ``(remaining, landed, advisories)``.

    The parser looks for the backlog section, then the ``#### Landed`` and
    ``#### Remaining frontier`` subsections nested under the current
    frontier heading. It extracts numbered list
    entries and captures the first ``YOK-N`` reference in each line.

    The parser is intentionally lenient:

    - Missing top-level section → returns empty lists + advisory.
    - Subsection present but no numbered entries → returns empty list
      + advisory.
    - Entry line without any YOK-N ref → skipped with advisory.
    - Multiple Remaining frontier subsections → all are concatenated.
    """
    from yoke_core.domain.master_plan_check import FrontierEntry

    advisories: List[str] = []
    remaining: List[FrontierEntry] = []
    landed: List[FrontierEntry] = []

    if not md_text.strip():
        advisories.append("MASTER-PLAN.md is empty.")
        return remaining, landed, advisories

    lines = md_text.splitlines()

    # Locate "## 5. Backlog By Generation" (tolerate different numbers).
    backlog_start: Optional[int] = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## ") and "Backlog By Generation" in stripped:
            backlog_start = i
            break
    if backlog_start is None:
        advisories.append(
            "No '## ... Backlog By Generation' section found — strategize "
            "cannot validate ordered frontier without it."
        )
        return remaining, landed, advisories

    # Walk forward collecting entries inside #### Landed / Remaining frontier
    # subsections until the next ``## `` heading. Modern MP versions may
    # expose the active frontier as phase-level bullets before concrete YOK-N
    # tickets are filed; keep those as a specific advisory instead of the old
    # generic "format changed" warning.
    current_section: Optional[str] = None
    rank_remaining = 0
    rank_landed = 0
    phase_bullets: List[str] = []

    for line in lines[backlog_start + 1:]:
        stripped = line.strip()

        # Stop at the next top-level section.
        if stripped.startswith("## ") and not stripped.startswith("### "):
            break

        if _PHASE_BULLET_RE.match(line):
            phase_bullets.append(stripped)

        # Track subsection transitions.
        if stripped.startswith("#### "):
            header = stripped[5:].strip().lower()
            if header.startswith("landed"):
                current_section = "landed"
            elif header.startswith("remaining"):
                current_section = "remaining"
            else:
                current_section = None
            continue

        if current_section is None:
            continue

        match = _NUMBERED_ENTRY_RE.match(line)
        if not match:
            continue

        entry_text = match.group(2)
        yok_ids = _yok_ids_in(entry_text)
        if not yok_ids:
            advisories.append(
                f"Numbered entry in '{current_section}' has no YOK-N ref: "
                f"{entry_text[:80]!r}"
            )
            continue

        # First YOK-N in the line is the primary id for that entry.
        primary = yok_ids[0]
        title = _strip_title(entry_text, primary)

        if current_section == "remaining":
            rank_remaining += 1
            remaining.append(
                FrontierEntry(
                    rank=rank_remaining,
                    yok_id=primary,
                    title=title,
                    section="remaining",
                    raw_line=line.rstrip(),
                )
            )
        else:
            rank_landed += 1
            landed.append(
                FrontierEntry(
                    rank=rank_landed,
                    yok_id=primary,
                    title=title,
                    section="landed",
                    raw_line=line.rstrip(),
                )
            )

    if not remaining and not landed:
        if phase_bullets:
            preview = ", ".join(
                bullet.lstrip("-* ").strip() for bullet in phase_bullets[:5]
            )
            suffix = "" if len(phase_bullets) <= 5 else ", ..."
            advisories.append(
                "Backlog By Generation section contains phase-level frontier "
                f"entries ({preview}{suffix}) but no numbered YOK-N entries; "
                "status-order validation is skipped until concrete tickets are filed."
            )
        else:
            advisories.append(
                "Backlog By Generation section found but no numbered "
                "frontier entries were parsed — plan format may have changed."
            )

    return remaining, landed, advisories


# Split on sentence boundaries but also on line breaks, since the plan
# uses long wrapped paragraphs. Use a simple regex rather than a full
# NLP sentence splitter — we only need to bound the search window.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def parse_prerequisite_prose(
    md_text: str,
) -> Tuple[List["ProseRelationship"], List["ProseRelationship"], List[str]]:
    """Extract prerequisite-style relationships from plan prose.

    Returns ``(unambiguous, ambiguous, advisories)``.

    - **Unambiguous**: exactly two distinct ``YOK-N`` refs on either
      side of a prerequisite keyword. The *right-hand* side is the
      dependent (it "depends on" / "builds on" the left-hand blocker),
      except for reversed keywords like ``prerequisite for`` where the
      subject is the blocker.
    - **Ambiguous**: three or more distinct ``YOK-N`` refs around one
      prerequisite keyword. These become advisories — the validator
      reports them to the operator but does not flag drift.
    """
    from yoke_core.domain.master_plan_check import ProseRelationship

    unambiguous: List[ProseRelationship] = []
    ambiguous: List[ProseRelationship] = []
    advisories: List[str] = []

    if not md_text.strip():
        return unambiguous, ambiguous, advisories

    sentences = _SENTENCE_SPLIT_RE.split(md_text)

    for raw in sentences:
        sentence = raw.strip()
        if not sentence:
            continue
        yok_ids = _yok_ids_in(sentence)
        if len(yok_ids) < 2:
            continue

        matched_keyword: Optional[str] = None
        lowered = sentence.lower()
        for kw in _PREREQ_KEYWORDS:
            if kw in lowered:
                matched_keyword = kw
                break
        if not matched_keyword:
            continue

        if len(yok_ids) >= 3:
            # Ambiguous — preserve the sentence for operator review but
            # do not infer a specific pair.
            ambiguous.append(
                ProseRelationship(
                    dependent=yok_ids[-1],
                    blocker=yok_ids[0],
                    keyword=matched_keyword,
                    snippet=sentence,
                )
            )
            continue

        left, right = yok_ids[0], yok_ids[1]
        # Direction: for ``prerequisite for`` / ``must come before`` /
        # ``enables`` / ``blocks`` / ``precondition for``, the left-hand
        # YOK-N is the blocker (it enables the right-hand dependent).
        # For ``depends on`` / ``builds on`` / ``built on`` /
        # ``prerequisite`` / ``requires`` / ``must not outrun`` /
        # ``prerequisite slice``, the left-hand YOK-N is the dependent
        # and the right-hand is the blocker.
        blocker_first_keywords = {
            "prerequisite for",
            "must come before",
            "precondition for",
            "blocks",
        }
        if matched_keyword in blocker_first_keywords:
            blocker, dependent = left, right
        else:
            dependent, blocker = left, right

        unambiguous.append(
            ProseRelationship(
                dependent=dependent,
                blocker=blocker,
                keyword=matched_keyword,
                snippet=sentence,
            )
        )

    return unambiguous, ambiguous, advisories

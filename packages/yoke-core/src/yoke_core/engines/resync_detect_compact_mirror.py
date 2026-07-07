"""Compact-mirror suppression helpers for the resync body detector.

The compact-mirror write contract lives in
:mod:`yoke_core.domain.backlog_github_body_budget`: when the locally
rendered item body exceeds the 62000-byte GitHub budget, the sync path
publishes a compact mirror that carries the deterministic footer below.

The detect side needs to recognise that contract — otherwise it byte-
compares the over-budget local body against the published compact
mirror and flags spurious drift on every run. This module owns the
detection-side predicates; :mod:`resync_detect_compare` calls them
from the body-comparison block.
"""

from __future__ import annotations

from yoke_core.domain.backlog_github_body_budget import (
    body_exceeds_budget,
    render_compact_mirror,
)
from yoke_core.engines.resync_detect_models import normalize_body_for_compare


COMPACT_MIRROR_FOOTER = (
    "_Body exceeded GitHub's size budget; full content stays in the DB._"
)


def _strip_evidence_section(body: str) -> str:
    """Strip the ``## Evidence`` section content for compact-mirror compare.

    The Evidence summary line is the one volatile element of the compact
    mirror (it reflects the latest event timestamp and re-renders on every
    sync). Suppressing the section content before comparison lets the
    detector treat two compact mirrors as equivalent when only the
    evidence event line differs. The heading itself stays so the section
    structure is still asserted; everything between the heading and the
    next blank line is dropped.
    """
    if not body or "## Evidence" not in body:
        return body
    lines = body.split("\n")
    out: list[str] = []
    in_evidence_content = False
    for line in lines:
        if in_evidence_content:
            if line.strip() == "":
                in_evidence_content = False
                out.append(line)
                continue
            if line.startswith("## ") or line.startswith("# "):
                in_evidence_content = False
                out.append(line)
                continue
            continue
        out.append(line)
        if line.strip() == "## Evidence":
            in_evidence_content = True
    return "\n".join(out)


def matches_compact_mirror(
    *,
    local_body: str,
    gh_body: str,
    item_fields: dict,
    item_id: int,
) -> bool:
    """Return True when the GH body matches the expected compact mirror.

    The contract: when the local body is over GitHub's body budget AND the
    GH body carries the deterministic compact-mirror footer, recompute
    what the compact mirror should be and check it matches what GitHub
    has, tolerating the volatile ``## Evidence`` event line.
    """
    if COMPACT_MIRROR_FOOTER not in (gh_body or ""):
        return False
    if not body_exceeds_budget(local_body or ""):
        return False
    expected = render_compact_mirror(
        item_fields, conn=None, item_id=item_id,
    )
    return (
        _strip_evidence_section(normalize_body_for_compare(expected))
        == _strip_evidence_section(normalize_body_for_compare(gh_body or ""))
    )


__all__ = [
    "COMPACT_MIRROR_FOOTER",
    "_strip_evidence_section",
    "matches_compact_mirror",
]

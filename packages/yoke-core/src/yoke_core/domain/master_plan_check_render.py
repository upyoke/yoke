"""Reporter helpers for ``master_plan_check``.

This module is the reporter leg of the parser/evaluator/reporter
triplet that backs ``yoke_core.domain.master_plan_check``. It owns
``render_report`` — convert a ``ValidationResult`` into the markdown
report consumed by the strategize research phase.

``ValidationResult`` is owned by the entry-point module; we import it
via a deferred local import inside the function to avoid a circular
import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from yoke_core.domain.master_plan_check import ValidationResult


def render_report(result: "ValidationResult") -> str:
    """Render a markdown report for the strategize research phase."""
    lines: List[str] = []
    lines.append("## MASTER-PLAN Frontier Validation")
    lines.append("")
    lines.append(
        f"Parsed {len(result.remaining_entries)} remaining frontier "
        f"entries and {len(result.landed_entries)} landed entries."
    )
    lines.append(
        f"Extracted {len(result.relationships)} unambiguous prerequisite "
        f"relationship(s) from plan prose "
        f"({len(result.ambiguous_relationships)} ambiguous)."
    )
    lines.append("")

    if result.contradictions:
        lines.append(f"### Contradictions ({len(result.contradictions)})")
        lines.append("")
        lines.append("| # | Kind | Earlier | Earlier status | Later | Later status | Detail |")
        lines.append("|---|------|---------|----------------|-------|--------------|--------|")
        for i, contra in enumerate(result.contradictions, start=1):
            lines.append(
                f"| {i} | {contra.kind} | {contra.earlier} | {contra.earlier_status} "
                f"| {contra.later} | {contra.later_status} | {contra.detail} |"
            )
        lines.append("")
    else:
        lines.append("### Contradictions")
        lines.append("")
        lines.append("_No concrete frontier or prerequisite-prose contradictions detected._")
        lines.append("")

    if result.ambiguous_relationships:
        lines.append(f"### Ambiguous prerequisite prose ({len(result.ambiguous_relationships)})")
        lines.append("")
        lines.append("These sentences contain three or more YOK-N references and a prerequisite keyword. Review manually:")
        lines.append("")
        for rel in result.ambiguous_relationships:
            lines.append(f"- `{rel.keyword}` — {rel.snippet}")
        lines.append("")

    if result.advisories:
        lines.append(f"### Advisories ({len(result.advisories)})")
        lines.append("")
        for note in result.advisories:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"

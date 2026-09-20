"""What a Browser case's assertions observed, and the verdict that follows.

An assertion is only evidence if it could have come out the other way. Three
of the checks the browser runner supports are satisfied by a page holding no
matching element at all: ``hidden`` (Playwright reports a detached locator as
hidden), ``count_eq`` of 0, and ``count_gte`` of 0. Each of those passes on a
screen it never observed. The runner decides them on a match count it already
has and reports a zero-match pass as ``vacuous_absence`` on the step result;
this module collects those reports and turns them into a verdict.

That set is derived from the runner's own assertion vocabulary rather than
invented here: ``visible``, ``text_contains``, ``text_equals`` and
``count_gte`` of one or more all fail against a zero-match locator, so none of
them can pass vacuously. A check added to that vocabulary has to be classified
the same way where the runner resolves it, instead of falling through as if it
were safe.

The rule below is a statement about the case, not about any one assertion,
because absence is often exactly what a case is about. A case that asserts a
control is gone at desktop width *and* asserts something the desktop layout
does show has observed a rendered page, so its absence assertion is a real
finding and stays a pass. A case whose only assertion is an absence guard that
matched nothing never saw the page at all — there was nothing for any of its
assertions to be wrong about — so it proved nothing and cannot be reported as
a pass. Same rule, opposite outcomes, and neither needs a judgement about what
the author meant: it reads only what the assertions resolved against at run
time.

Browser checks decide automatically here. Browser inspections stay
verdict-less until the plan's batch reviewer, so for those the vacuity travels
into the evidence instead — the run payload and each capture's metadata —
where the person judging the bundle will see it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Field the browser runner reports a zero-match absence pass under.
VACUOUS_ABSENCE_FIELD = "vacuous_absence"


def describe_vacuous(reports: List[Dict[str, Any]]) -> str:
    """Name the assertions that matched nothing, for a reader of the run."""
    return ", ".join(
        f"{report.get('check')} {report.get('target')}" for report in reports
    )


@dataclass
class CaseAssertions:
    """Every assertion one Browser case declared, and what each observed."""

    declared: int = 0
    passed: int = 0
    vacuous: List[Dict[str, Any]] = field(default_factory=list)

    def declare(self) -> None:
        """Count one assertion step the case asked for."""
        self.declared += 1

    def record_pass(self, step_data: Any) -> None:
        """Count one assertion that passed, and whether it saw anything."""
        self.passed += 1
        report = (
            step_data.get(VACUOUS_ABSENCE_FIELD)
            if isinstance(step_data, dict)
            else None
        )
        if isinstance(report, dict):
            self.vacuous.append(report)

    @property
    def rests_on_vacuity(self) -> bool:
        """Whether nothing this case asserted ever matched an element."""
        return bool(self.vacuous) and len(self.vacuous) == self.passed

    def verdict_failure(self, requirement_id: int) -> Optional[str]:
        """Why this case cannot be called a pass, or None when it can."""
        if self.passed != self.declared:
            return (
                "assertion_completeness:"
                f"expected={self.declared},passed={self.passed};"
            )
        if self.rests_on_vacuity:
            return (
                "assertion_vacuous_absence:every assertion in this case "
                f"({describe_vacuous(self.vacuous)}) resolved against a "
                "locator that matched zero elements, so none of them could "
                "have failed and the case proved nothing about the page. Add "
                "one assertion for something the route does render — the "
                "container the absent element would live in, or any element "
                "the page always shows — so the absence is read off a screen "
                "that rendered: yoke qa requirement update --requirement-id "
                f"{requirement_id} --field method_config --stdin, then yoke "
                f"qa case run --requirement-id {requirement_id};"
            )
        return None


__all__ = [
    "VACUOUS_ABSENCE_FIELD",
    "CaseAssertions",
    "describe_vacuous",
]

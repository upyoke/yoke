"""HC-skill-entrypoint-disclosure — a `/yoke` entrypoint routes, it does not teach.

Every `/yoke <command>` is entered through `<command>/SKILL.md`, and that file
is read on every invocation and again on every resume. Detail that only one
phase needs belongs in the file that phase reads, so this check holds three
properties and reports the measurement behind them:

A. **Budget.** Each entrypoint stays within
   :data:`yoke_contracts.startup_context_budget.SKILL_ENTRYPOINT_BYTES`. The
   phase references it names are deliberately unbounded.
B. **Routing.** A command with phase references carries a phase map, and does
   not order a phase file read *completely* from the entrypoint — a split that
   still tells every caller to read everything is not a split.
C. **Reachability.** Every phase reference is reachable by following citations
   *from the entrypoint*, so nothing is orphaned by a rename. A union over
   every sibling's citations would let two orphans cite each other and pass.

The detail line always carries the per-command byte measurement, so
`yoke watch doctor -- --only skill-entrypoint-disclosure` is both the gate and
the before/after number.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from yoke_contracts.startup_context_budget import (
    SKILL_ENTRYPOINT_BYTES,
    budget_phrase,
)
from yoke_core.engines.doctor_applicability import NOT_APPLICABLE
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector, _resolve_repo_root


HC_SLUG = "HC-skill-entrypoint-disclosure"
HC_LABEL = "Skill entrypoint over budget, missing its phase map, or orphaning a reference"

SKILL_ROOT = ".agents/skills/yoke"
ENTRYPOINT = "SKILL.md"

#: A command whose entrypoint is the whole command. These have no phase
#: references, so there is nothing for a phase map to route to.
_ROUTING_MARKERS = ("Phase map", "Step map", "Phased-Read Plan")

# A citation may be a bare name, a sibling link, or a full repo path; the
# reachability question is the same either way, so match the basename.
_MD_CITATION = re.compile(r"(?P<name>[A-Za-z0-9_.-]+\.md)")


def _commands(skills_root: Path) -> list[Path]:
    return sorted(
        directory
        for directory in skills_root.iterdir()
        if directory.is_dir() and (directory / ENTRYPOINT).is_file()
    )


def _phase_references(command: Path) -> list[Path]:
    return sorted(p for p in command.glob("*.md") if p.name != ENTRYPOINT)


def _cited_names(text: str) -> set[str]:
    return {match.group("name") for match in _MD_CITATION.finditer(text)}


def _reachable_from_entrypoint(entry_text: str, references: list[Path]) -> set[str]:
    """Return the references a reader can arrive at by following citations.

    Reachability is a walk that *starts at the entrypoint*, not a union of
    every file's citations. Unioning lets a pair of orphans cite each other —
    or a file cite itself — and count as reached, which is exactly the shape a
    rename strands: nothing on the routed path names either one.
    """
    by_name = {reference.name: reference for reference in references}
    reached: set[str] = set()
    frontier = _cited_names(entry_text) & set(by_name)
    while frontier:
        name = frontier.pop()
        if name in reached:
            continue
        reached.add(name)
        cited = _cited_names(
            by_name[name].read_text(encoding="utf-8", errors="replace")
        )
        frontier |= (cited & set(by_name)) - reached
    return reached


def _scan(repo_root: Path) -> tuple[List[str], List[str]]:
    """Return (findings, measurements) for every `/yoke` command."""
    skills_root = repo_root / SKILL_ROOT
    findings: List[str] = []
    measurements: List[str] = []
    if not skills_root.is_dir():
        return findings, measurements

    for command in _commands(skills_root):
        entry = command / ENTRYPOINT
        text = entry.read_text(encoding="utf-8", errors="replace")
        size = len(text.encode("utf-8"))
        references = _phase_references(command)
        measurements.append(f"{command.name}={size}")

        if size > SKILL_ENTRYPOINT_BYTES:
            findings.append(
                f"- {SKILL_ROOT}/{command.name}/{ENTRYPOINT}: entrypoint spends "
                f"{budget_phrase(size, SKILL_ENTRYPOINT_BYTES)}. Move the detail "
                "only one phase needs into the file that phase reads."
            )

        if not references:
            continue

        if not any(marker in text for marker in _ROUTING_MARKERS):
            findings.append(
                f"- {SKILL_ROOT}/{command.name}/{ENTRYPOINT}: has "
                f"{len(references)} phase reference(s) but no phase map. Name "
                "each one beside the phase that reads it."
            )

        for lineno, line in enumerate(text.splitlines(), start=1):
            if "completely" in line and _MD_CITATION.search(line):
                findings.append(
                    f"- {SKILL_ROOT}/{command.name}/{ENTRYPOINT}:{lineno}: orders "
                    "a phase reference read 'completely' from the entrypoint. "
                    "Route to it at its phase instead."
                )

        reachable = _reachable_from_entrypoint(text, references)
        for reference in references:
            if reference.name not in reachable:
                findings.append(
                    f"- {SKILL_ROOT}/{command.name}/{reference.name}: no citation "
                    "path reaches it from the entrypoint — a reader can never "
                    "arrive at it."
                )

    return findings, measurements


def hc_skill_entrypoint_disclosure(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-skill-entrypoint-disclosure: entrypoints route, phase files teach."""
    repo_root = _resolve_repo_root()
    if not repo_root:
        # Not a pass: this runner could not read the corpus, so it answered
        # nothing. The applicability declaration already keeps the check off
        # checkout-less runners; this is the same verdict stated in-check.
        rec.record(
            HC_SLUG,
            HC_LABEL,
            NOT_APPLICABLE,
            "reads this project's skill corpus; no repo root is resolvable on "
            "this runner",
        )
        return

    findings, measurements = _scan(Path(repo_root))
    total = sum(int(entry.split("=")[1]) for entry in measurements)
    measured = (
        f"{len(measurements)} entrypoints, {total} bytes total "
        f"(budget {SKILL_ENTRYPOINT_BYTES} each): " + " ".join(measurements)
    )
    if findings:
        rec.record(HC_SLUG, HC_LABEL, "FAIL", "\n".join(findings) + "\n" + measured)
    else:
        rec.record(HC_SLUG, HC_LABEL, "PASS", measured)


__all__ = [
    "hc_skill_entrypoint_disclosure",
    "HC_SLUG",
    "HC_LABEL",
    "SKILL_ROOT",
]

from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        'skill-entrypoint-disclosure',
        'Skill entrypoint over budget, missing its phase map, or orphaning a reference',
        hc_skill_entrypoint_disclosure,
    ),
)

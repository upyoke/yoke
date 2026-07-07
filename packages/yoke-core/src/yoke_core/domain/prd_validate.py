"""PRD validation quality gate.

Direct Python owner — invoked via ``python3 -m yoke_core.domain.prd_validate``.
DB path resolution delegates to
:func:`yoke_core.domain.db_helpers.resolve_db_path`, so callers set
``YOKE_DB`` (or rely on the canonical resolver) rather than pointing the
validator at a specific repo root.

Section/item extraction lives in :mod:`yoke_core.domain.prd_validate_extract`,
content-quality predicates in :mod:`yoke_core.domain.prd_validate_checks`,
and the report printer in :mod:`yoke_core.domain.prd_validate_render`.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

from yoke_core.domain import db_helpers
from yoke_core.domain.prd_validate_checks import (
    build_actionable_text,
    has_cleanup_coverage,
    has_discovery_guidance,
    has_failure_recovery_coverage,
    has_measurable_language,
    needs_cleanup_coverage,
    needs_discovery_guidance,
    needs_failure_recovery,
)
from yoke_core.domain.prd_validate_extract import (
    count_list_items,
    extract_section,
    extract_section_fuzzy,
    has_content,
    normalize_item_ref,
)
from yoke_core.domain.prd_validate_render import print_report


@dataclass
class Report:
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    passed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def record(self, check_id: str, name: str, result: str, detail: str, guidance: str = "") -> None:
        line = f"{result}: {check_id} {name} -- {detail}"
        if guidance:
            line = f"{line}\n    Fix: {guidance}"
        if result == "PASS":
            self.pass_count += 1
            self.passed.append(line)
        elif result == "WARN":
            self.warn_count += 1
            self.warnings.append(line)
        elif result == "FAIL":
            self.fail_count += 1
            self.failures.append(line)
        else:
            raise ValueError(f"unknown result type: {result}")


def resolve_body(item_ref: Optional[str], body_text: Optional[str]) -> tuple[str, str]:
    if body_text is not None:
        return body_text, item_ref or "inline"
    if not item_ref:
        raise SystemExit(
            "Usage: python3 -m yoke_core.domain.prd_validate <YOK-N|N> [--strict]\n"
            "       python3 -m yoke_core.domain.prd_validate --body-text <text>\n"
            "       echo \"$body\" | python3 -m yoke_core.domain.prd_validate --body-text -"
        )

    num = normalize_item_ref(item_ref)
    item_label = f"YOK-{num}"

    conn = db_helpers.connect()
    try:
        spec_row = conn.execute(
            "SELECT spec FROM items WHERE id=%s", (num,),
        ).fetchone()
        spec_body = spec_row[0] if spec_row and spec_row[0] is not None else ""
        spec_body = "" if str(spec_body) == "null" else str(spec_body)
        if not has_content(spec_body):
            # render body on demand (body column retired)
            from yoke_core.domain.render_body import build_body
            body = build_body(conn, num) or ""
        else:
            body = spec_body
    finally:
        conn.close()

    body = "" if str(body) == "null" else str(body)
    if not has_content(body):
        print(f"FAIL: Item {item_label} has no spec or body content. Write a PRD first.", file=sys.stderr)
        raise SystemExit(1)
    return body, item_label


def validate_prd(body: str, item_label: str) -> Report:
    report = Report()
    rec = report.record

    problem = (
        extract_section_fuzzy(body, "Problem")
        or extract_section_fuzzy(body, "Why now")
        or extract_section_fuzzy(body, "Motivation")
        or extract_section_fuzzy(body, "Background")
    )
    if not problem:
        rec("PRD-1", "Problem/Why", "FAIL", "No Problem Statement section found.",
            "Add a '## Problem Statement' section explaining why this work matters.")
    elif has_content(problem):
        problem_len = len("".join(line for line in problem.splitlines() if line.strip()))
        if problem_len < 20:
            rec("PRD-1", "Problem/Why", "FAIL", f"Problem Statement is too brief ({problem_len} chars).",
                "Expand the Problem Statement to articulate a clear 'why' -- what pain exists and for whom.")
        else:
            rec("PRD-1", "Problem/Why", "PASS", "Problem Statement section found with substantive content.")
    else:
        rec("PRD-1", "Problem/Why", "FAIL", "Problem Statement section exists but is empty.",
            "Fill in the Problem Statement with a clear explanation of why this work matters.")

    requirements = extract_section_fuzzy(body, "Functional Requirements") or extract_section_fuzzy(body, "Requirements")
    if not requirements:
        rec("PRD-2", "Requirements", "FAIL", "No Requirements section found.",
            "Add a '## Requirements' section with at least one testable functional requirement (e.g., 'FR-1: ...').")
    elif has_content(requirements):
        req_count = count_list_items(requirements)
        fr_count = len(re.findall(r"(FR-[0-9]+|[0-9]+\.)", requirements))
        total_reqs = max(req_count, fr_count)
        if total_reqs > 0:
            rec("PRD-2", "Requirements", "PASS", f"Requirements section found with {total_reqs} item(s).")
        else:
            rec("PRD-2", "Requirements", "FAIL", "Requirements section exists but contains no testable requirements.",
                "Add numbered requirements (e.g., 'FR-1: The system shall...') or bulleted items.")
    else:
        rec("PRD-2", "Requirements", "FAIL", "Requirements section exists but is empty.",
            "Add at least one testable functional requirement.")

    metrics = (
        extract_section_fuzzy(body, "Success Metrics")
        or extract_section_fuzzy(body, "Success Criteria")
        or extract_section_fuzzy(body, "Metrics")
    )
    if not metrics:
        rec("PRD-3", "Success Metrics", "FAIL", "No Success Metrics section found.",
            "Add a '## Success Metrics' section defining how you will know this work succeeded.")
    elif has_content(metrics):
        if has_measurable_language(metrics):
            rec("PRD-3", "Success Metrics", "PASS", "Success Metrics section found with measurable criteria.")
        else:
            rec("PRD-3", "Success Metrics", "WARN",
                "Success Metrics section exists but may lack measurable criteria.",
                "Add concrete targets: numbers, percentages, time bounds, or specific measurable outcomes.")
    else:
        rec("PRD-3", "Success Metrics", "FAIL", "Success Metrics section exists but is empty.",
            "Define how you will measure success -- include numbers, targets, or specific outcomes.")

    open_questions = extract_section_fuzzy(body, "Open Questions")
    if open_questions and has_content(open_questions):
        oq_count = count_list_items(open_questions)
        if oq_count > 0:
            rec("PRD-4", "Open Questions", "WARN", f"{oq_count} unresolved open question(s) remain.",
                "Resolve open questions before planning, or move them to a 'Resolved Questions' section.")
        else:
            stripped = "\n".join(
                line for line in open_questions.splitlines()
                if line.strip() and line.strip().lower() not in {"none", "n/a"}
            )
            if stripped:
                rec("PRD-4", "Open Questions", "WARN",
                    "Open Questions section has content that may need resolution.",
                    "Review the Open Questions section and resolve or remove items before planning.")
            else:
                rec("PRD-4", "Open Questions", "PASS", "Open Questions section is empty or marked as resolved.")
    else:
        rec("PRD-4", "Open Questions", "PASS", "No unresolved open questions.")

    goals = extract_section_fuzzy(body, "Goals")
    if not goals:
        rec("PRD-5", "Goals", "FAIL", "No Goals section found.",
            "Add a '## Goals' section with concrete, measurable outcomes.")
    elif has_content(goals):
        goal_count = count_list_items(goals)
        if goal_count > 0:
            if has_measurable_language(goals):
                rec("PRD-5", "Goals", "PASS",
                    f"Goals section found with {goal_count} goal(s) containing measurable language.")
            else:
                rec("PRD-5", "Goals", "WARN",
                    f"Goals section has {goal_count} goal(s) but may lack measurable criteria.",
                    "Make goals measurable: include numbers, timeframes, or specific observable outcomes.")
        else:
            rec("PRD-5", "Goals", "WARN", "Goals section exists but contains no bulleted/numbered goals.",
                "Structure goals as a bulleted list with measurable outcomes.")
    else:
        rec("PRD-5", "Goals", "FAIL", "Goals section exists but is empty.", "Add concrete, measurable goals.")

    actionable = build_actionable_text(body)
    if needs_failure_recovery(actionable):
        if has_failure_recovery_coverage(actionable):
            rec("PRD-6", "Failure/Recovery", "PASS", "State-changing work includes failure or recovery coverage.")
        else:
            rec("PRD-6", "Failure/Recovery", "FAIL",
                "State-changing work is missing failure/recovery coverage.",
                "Add a '## Failure and Recovery' section or explicit requirements/ACs covering what can fail, what state is left behind, and how recovery works.")
    else:
        rec("PRD-6", "Failure/Recovery", "PASS", "No explicit state-changing operation detected.")

    if needs_cleanup_coverage(actionable):
        if has_cleanup_coverage(actionable):
            rec("PRD-7", "Cleanup Coverage", "PASS", "Replacement/removal work includes cleanup guidance.")
        else:
            rec("PRD-7", "Cleanup Coverage", "FAIL",
                "Replacement/removal work is missing explicit cleanup coverage.",
                "Add a '## Cleanup and Removal' section or acceptance criteria covering dead code, docs, tests, config, and compatibility paths that must disappear.")
    else:
        rec("PRD-7", "Cleanup Coverage", "PASS", "No replacement/removal trigger detected.")

    if needs_discovery_guidance(actionable):
        if has_discovery_guidance(actionable):
            rec("PRD-8", "Blast Radius Discovery", "PASS",
                "Spec includes discovery-oriented blast radius guidance.")
        else:
            rec("PRD-8", "Blast Radius Discovery", "FAIL",
                "Rename/removal-heavy work lacks discovery-oriented blast radius guidance.",
                "Add a '## Blast Radius' section or acceptance criteria telling downstream agents to use grep/rg to find all affected consumers and residue.")
    else:
        rec("PRD-8", "Blast Radius Discovery", "PASS", "No rename/removal-heavy trigger detected.")

    ac_canonical_count = len(re.findall(r"^\- \[ \] AC-", body, re.MULTILINE))
    if ac_canonical_count > 0:
        rec("PRD-9", "Acceptance Criteria", "PASS", f"{ac_canonical_count} canonical AC checkbox(es) found.")
    else:
        ac_section = extract_section(body, "Acceptance Criteria")
        ac_unlabeled_count = len(re.findall(r"^\- \[ \] ", ac_section, re.MULTILINE)) if has_content(ac_section) else 0
        if ac_unlabeled_count > 0:
            rec("PRD-9", "Acceptance Criteria", "WARN",
                f"{ac_unlabeled_count} unlabeled AC checkbox(es) under ## Acceptance Criteria.",
                "Use canonical format: '- [ ] AC-N: {description}' for each acceptance criterion.")
        else:
            rec("PRD-9", "Acceptance Criteria", "FAIL", "No acceptance criteria checkboxes found.",
                "Add a '## Acceptance Criteria' section with '- [ ] AC-1: {description}' checkboxes. Each AC must be specific and independently testable.")

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prd-validate",
        description="Validate PRD/spec quality before planning",
    )
    parser.add_argument("item_ref", nargs="?")
    parser.add_argument("--body-text")
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    body_text = None
    if args.body_text is not None:
        body_text = sys.stdin.read() if args.body_text == "-" else args.body_text
    try:
        body, item_label = resolve_body(args.item_ref, body_text)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            sys.exit(2)
        raise

    report = validate_prd(body, item_label)
    print_report(item_label, report)
    if report.fail_count > 0:
        sys.exit(1)
    if args.strict and report.warn_count > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

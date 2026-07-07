"""Content-quality predicates for PRD validation.

Sibling of :mod:`yoke_core.domain.prd_validate`. Owns the trigger and
coverage predicates (failure/recovery, cleanup, blast-radius discovery,
measurable language) that drive the validator's recommendations.
"""

from __future__ import annotations

import re

from yoke_core.domain.prd_validate_extract import (
    extract_section_fuzzy,
    has_content,
)


MEASURABLE_PATTERN = re.compile(
    r"reduce|increase|improve|decrease|eliminate|automate|validate|verify|ensure|prevent|detect|measure|track|count|percentage|ratio|rate|time|latency|throughput|error|score|target|threshold|baseline|benchmark|SLA|KPI|OKR|metric|quantif|[0-9]",
    re.IGNORECASE,
)


def has_measurable_language(text: str) -> bool:
    return bool(MEASURABLE_PATTERN.search(text))


def contains_pattern(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, re.IGNORECASE))


def build_actionable_text(body: str) -> str:
    sections = []
    for name in (
        "Goals",
        "Requirements",
        "Success Metrics",
        "Success Criteria",
        "Acceptance Criteria",
        "Blast Radius",
        "Cleanup",
        "Removal",
        "Failure",
        "Recovery",
        "Rollback",
    ):
        content = extract_section_fuzzy(body, name)
        if has_content(content):
            sections.append(content)
    return "\n".join(sections) if sections else body


def needs_failure_recovery(text: str) -> bool:
    return contains_pattern(
        text,
        r"(deploy|deployment|merge|migrat|rename|remove|delete|drop|backfill|status transition|approval|release|schema|table|column|sync)",
    )


def has_failure_recovery_coverage(text: str) -> bool:
    if any(
        has_content(extract_section_fuzzy(text, name))
        for name in ("Failure", "Recovery", "Rollback")
    ):
        return True
    return contains_pattern(
        text,
        r"(on failure|failure path|if .* fail|if .* fails|rollback plan|rollback to|recover by|recovery steps|retry plan|partial state|restore from|revert to|error handling)",
    )


def needs_cleanup_coverage(text: str) -> bool:
    return contains_pattern(text, r"(rename|replace|remove|delete|drop|deprecat|legacy|supersed|obsolete)")


def has_cleanup_coverage(text: str) -> bool:
    if any(
        has_content(extract_section_fuzzy(text, name))
        for name in ("Cleanup", "Removal")
    ):
        return True
    return contains_pattern(
        text,
        r"(cleanup|clean up|remove old|remove legacy|delete old|delete legacy|dead code|compatibility shim|update docs|update documentation|update help text|update tests|residue grep)",
    )


def needs_discovery_guidance(text: str) -> bool:
    return contains_pattern(text, r"(rename|replace|remove|delete|drop|migrat|signature|interface|config key)")


def has_discovery_guidance(text: str) -> bool:
    blast = extract_section_fuzzy(text, "Blast Radius")
    pattern = r"(grep -r|rg |all consumers|all callers|find all references|blast radius|residue grep|zero remaining references)"
    if has_content(blast) and contains_pattern(blast, pattern):
        return True
    return contains_pattern(text, pattern)

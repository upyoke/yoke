"""Shared helpers for the prd_validate pytest suites.

Named outside the ``test_*.py`` collection pattern so pytest does not pick it
up as a test module; the prd_validate test files import the fixtures below.
"""

from __future__ import annotations

from yoke_core.domain import prd_validate


COMPLETE_PRD = """# Spec: Test Feature

## Problem Statement
Users cannot validate PRD quality before planning, leading to vague tasks
and wasted Architect cycles. This affects all items entering the planning pipeline.

## Goals
- Reduce planning rework by 50% through pre-validation
- Ensure every PRD has measurable success criteria before Architect runs

## Non-Goals
- We will not validate technical implementation details
- We will not replace human judgment

## Requirements

### Functional Requirements
1. FR-1: Validate Problem Statement section exists and is non-empty
2. FR-2: Validate functional requirements section has at least one item
3. FR-3: Validate success metrics section exists with measurable criteria
4. FR-4: Warn if Open Questions section has unresolved items
5. FR-5: Validate Goals section exists with concrete outcomes

### Non-Functional Requirements
1. NFR-1: Validation completes in under 1 second

## Success Metrics
- 80% reduction in planning rework caused by vague PRDs
- Zero PRDs reaching Architect without Problem Statement
- All PRDs have at least one measurable success metric

## Open Questions
None

## Acceptance Criteria
- [ ] AC-1: Validator blocks PRDs missing required sections before planning
- [ ] AC-2: Validator reports measurable goals and success metrics"""


DEFAULT_AC_BLOCK = (
    "\n\n## Acceptance Criteria\n"
    "- [ ] AC-1: Validate the PRD structure for this scenario.\n"
)


def _with_default_acs(body: str) -> str:
    if "- [ ] AC-" in body:
        return body
    return body + DEFAULT_AC_BLOCK


def _validate(body: str) -> prd_validate.Report:
    return prd_validate.validate_prd(body, "YOK-test")

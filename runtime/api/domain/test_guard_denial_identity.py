"""Class-wide contracts for registered guard denial identities."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.hook_runner.denial_identity import check_id_line
from yoke_contracts.hook_runner.hook_guard_catalog import (
    GUARD_CATALOG,
    NESTED_CLAUDE_CLI_CHECK_ID,
)
from yoke_core.hooks.guard_denial_identity import bind
from yoke_core.hooks.types import HookDecision, Next, Outcome


def _deny(check_id: str = "") -> HookDecision:
    audit = {"check_id": check_id} if check_id else {}
    return HookDecision(
        outcome=Outcome.DENY,
        message=json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "BLOCKED: representative guard. Recover here.",
                }
            }
        ),
        audit_fields=audit,
        block=True,
        next=Next.STOP,
    )


@pytest.mark.parametrize("spec", GUARD_CATALOG, ids=lambda spec: spec.guard)
def test_every_registered_guard_reports_its_registered_check_id(spec) -> None:
    bound = bind(_deny(), spec.module)

    assert spec.check_id
    assert bound.audit_fields["check_id"] == spec.check_id
    assert check_id_line(spec.check_id) in bound.message


@pytest.mark.parametrize("spec", GUARD_CATALOG, ids=lambda spec: spec.guard)
def test_registered_guard_cannot_report_another_guards_check_id(spec) -> None:
    foreign = next(
        candidate.check_id
        for candidate in GUARD_CATALOG
        if candidate.check_id not in spec.report_check_ids
    )

    bound = bind(_deny(foreign), spec.module)

    assert bound.audit_fields["check_id"] == spec.check_id
    assert bound.audit_fields["reported_check_id_mismatch"] == foreign
    assert check_id_line(spec.check_id) in bound.message
    assert check_id_line(foreign) not in bound.message


def test_registered_primary_check_ids_are_nonempty_and_unique() -> None:
    check_ids = [spec.check_id for spec in GUARD_CATALOG]
    assert all(check_ids)
    assert len(check_ids) == len(set(check_ids))


def test_db_command_guard_accepts_registered_nested_claude_check_id() -> None:
    spec = next(spec for spec in GUARD_CATALOG if spec.guard == "lint_db_cmd")
    bound = bind(_deny(NESTED_CLAUDE_CLI_CHECK_ID), spec.module)

    assert bound.audit_fields["check_id"] == NESTED_CLAUDE_CLI_CHECK_ID
    assert check_id_line(NESTED_CLAUDE_CLI_CHECK_ID) in bound.message

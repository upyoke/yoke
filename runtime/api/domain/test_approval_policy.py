"""The one approval policy parser every declaration surface validates through."""

from __future__ import annotations

import pytest

from yoke_core.domain.approval_policy import (
    ApprovalPolicy,
    approval_policy_or_none,
    parse_approval_policy,
)


def test_policy_without_a_mode_keeps_the_meaning_it_was_written_with():
    policy = parse_approval_policy(
        {"roles": ["owner"], "actors": [7]},
        path="policies.approval_defaults.done",
    )
    assert policy == ApprovalPolicy(roles=("owner",), actors=(7,), mode="any")
    assert policy.requires_every_approver is False
    assert policy.box_count == 2
    assert policy.describe() == "project owner or actor 7"


def test_all_mode_is_declared_and_described_as_every_approver():
    policy = parse_approval_policy(
        {"roles": ["operator", "owner"], "actors": [], "mode": "all"},
        path="stage 'approve-prod' approvals",
    )
    assert policy.requires_every_approver is True
    assert policy.describe() == "project operator and project owner"


@pytest.mark.parametrize(
    ("raw", "message"),
    (
        ({"mode": "some", "roles": ["owner"]}, "mode must be one of"),
        ({"roles": ["owner"], "tiers": []}, "unknown fields"),
        ({"roles": ["captain"]}, "unknown values"),
        ({"roles": ["owner", "owner"]}, "unique role names"),
        ({"actors": [0]}, "positive integer actor ids"),
        ({"actors": [True]}, "positive integer actor ids"),
        ({"roles": [], "actors": []}, "at least one role or actor"),
        ("owner", "must be an object"),
    ),
)
def test_invalid_policy_names_the_path_and_the_field_at_fault(raw, message):
    with pytest.raises(ValueError, match=message) as failure:
        parse_approval_policy(raw, path="policies.approval_defaults.done")
    assert "policies.approval_defaults.done" in str(failure.value)


def test_nothing_checked_is_no_gate_rather_than_an_empty_one():
    assert approval_policy_or_none({}, path="p") is None
    assert approval_policy_or_none(None, path="p") is None
    assert approval_policy_or_none({"roles": [], "actors": []}, path="p") is None
    assert approval_policy_or_none({"roles": ["owner"]}, path="p") == (
        ApprovalPolicy(roles=("owner",))
    )

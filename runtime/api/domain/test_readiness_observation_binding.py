"""What makes an observation from another host trustworthy, and what does not.

The file-reading readiness checks can run on a machine the control plane
never sees. That is only safe while the answer provably describes the
spec the control plane holds and a tree that held still, so each way
those can drift is covered here: every one of them has to come back
unperformed, never passed.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.idea_readiness_checkout import CHECKOUT_DEPENDENT_CHECKS
from yoke_core.domain.idea_readiness_local_inputs import (
    INCOMPLETE_REASON,
    MOVED_CHECKOUT_REASON,
    STALE_SPEC_REASON,
    UNVERIFIABLE_REVISION_REASON,
    binding_mismatch_reason,
    findings_from_observations,
    spec_digest,
)

_SPEC = "Modify `yoke_core.domain.some_module.some_function` so it streams.\n"

_ISSUE = {
    "code": "STALE_LINE_COUNT",
    "message": "spec records 10 lines but the file currently has 40",
    "remediation": "refresh the File Budget sizing",
    "context": {"path": "a.py"},
}


def _observations(**overrides) -> dict:
    base = {
        "spec_sha256": spec_digest(_SPEC),
        "checks": list(CHECKOUT_DEPENDENT_CHECKS),
        "checkout_path": "/checkout",
        "checkout_revision": "abc123+deadbeef",
        "checkout_moved": False,
        "issues": [],
        "advisories": [],
    }
    base.update(overrides)
    return base


def test_bound_observations_are_accepted() -> None:
    assert binding_mismatch_reason(_observations(), _SPEC) == ""


def test_a_spec_rewritten_since_the_request_is_not_a_pass() -> None:
    """The observing host read a spec the control plane no longer holds."""
    reason = binding_mismatch_reason(_observations(), _SPEC + "\nnew section\n")

    assert reason == STALE_SPEC_REASON


def test_a_tree_edited_mid_check_is_not_a_pass() -> None:
    reason = binding_mismatch_reason(_observations(checkout_moved=True), _SPEC)

    assert reason == MOVED_CHECKOUT_REASON


def test_an_unreadable_revision_is_not_a_pass() -> None:
    """Without a revision nothing proves the tree held still."""
    reason = binding_mismatch_reason(_observations(checkout_revision=""), _SPEC)

    assert reason == UNVERIFIABLE_REVISION_REASON


@pytest.mark.parametrize(
    "observations",
    [
        _observations(checks=[]),
        _observations(checks=list(CHECKOUT_DEPENDENT_CHECKS)[:2]),
        "not-a-mapping",
    ],
)
def test_a_check_not_reported_stays_unperformed(observations) -> None:
    assert binding_mismatch_reason(observations, _SPEC) == INCOMPLETE_REASON


def test_findings_pass_through_when_the_binding_holds() -> None:
    issues, advisories, unavailable = findings_from_observations(
        _observations(issues=[_ISSUE], advisories=[{"code": "SYMLINK_HINT"}]),
        _SPEC,
        item_ref="YOK-1",
    )

    assert [issue.code for issue in issues] == ["STALE_LINE_COUNT"]
    assert issues[0].context == {"path": "a.py"}
    assert advisories == [{"code": "SYMLINK_HINT"}]
    assert unavailable == []


def test_a_broken_binding_discards_the_findings_it_carried() -> None:
    """A stale answer's issues are as untrustworthy as its passes."""
    issues, advisories, unavailable = findings_from_observations(
        _observations(issues=[_ISSUE], checkout_moved=True),
        _SPEC,
        item_ref="YOK-1",
    )

    assert issues == []
    assert advisories == []
    assert [u.check for u in unavailable] == list(CHECKOUT_DEPENDENT_CHECKS)


def test_every_unperformed_check_names_its_cause_and_a_way_forward() -> None:
    _issues, _advisories, unavailable = findings_from_observations(
        _observations(checkout_moved=True), _SPEC, item_ref="YOK-1",
    )

    for entry in unavailable:
        assert entry.reason == MOVED_CHECKOUT_REASON
        assert entry.check in entry.recovery
        assert "YOK-1" in entry.recovery
        # Something moved; the same command run again can settle it.
        assert entry.retryable is True

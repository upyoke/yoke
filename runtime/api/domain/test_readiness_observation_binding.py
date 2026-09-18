"""What makes an answer from another host trustworthy, and what does not.

The file-reading readiness checks can run on a machine the control plane
never sees. That is only safe while the answer provably describes this
item's current spec, and while every finding in it is one those checks
could actually have produced. Each way either can drift is covered here:
all of them have to come back unperformed, never passed.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.idea_readiness_checkout import CHECKOUT_DEPENDENT_CHECKS
from yoke_core.domain.idea_readiness_local_inputs import spec_digest
from yoke_core.domain.idea_readiness_observation_binding import (
    INCOMPLETE_REASON,
    MOVED_CHECKOUT_REASON,
    STALE_SPEC_REASON,
    UNADMISSIBLE_FINDING_REASON,
    UNRECOGNIZED_CHECK_REASON,
    UNVERIFIABLE_REVISION_REASON,
    WRONG_ITEM_REASON,
    ObservationBinding,
    binding_mismatch_reason,
    findings_from_observations,
)

_BUDGET_PATH = "packages/yoke-core/src/yoke_core/domain/a.py"
_SPEC = (
    "Modify `yoke_core.domain.some_module.some_function` so it streams.\n"
    "\n"
    "## File Budget\n\n"
    f"- `{_BUDGET_PATH}` — current 10 lines; remaining headroom 340; "
    "at-or-over-limit: false; responsibility: streaming.\n"
)

_BINDING = ObservationBinding(item_id=1, project_id=7, spec_text=_SPEC)

_ISSUE = {
    "code": "STALE_LINE_COUNT",
    "message": "spec records 10 lines but the file currently has 40",
    "remediation": "refresh the File Budget sizing",
    "context": {"path": _BUDGET_PATH, "recorded": 10, "actual": 40},
}


def _observations(**overrides) -> dict:
    base = {
        "item_id": 1,
        "project_id": 7,
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
    assert binding_mismatch_reason(_observations(), _BINDING) == ""


def test_a_spec_rewritten_since_the_request_is_not_a_pass() -> None:
    """The observing host read a spec the control plane no longer holds."""
    drifted = ObservationBinding(
        item_id=1, project_id=7, spec_text=_SPEC + "\nnew section\n",
    )

    assert binding_mismatch_reason(_observations(), drifted) == STALE_SPEC_REASON


@pytest.mark.parametrize(
    "observations",
    [_observations(item_id=2), _observations(project_id=9)],
)
def test_an_answer_about_another_item_cannot_stand_in(observations) -> None:
    """Two items can hold identical spec text, so the digest is not enough."""
    assert binding_mismatch_reason(observations, _BINDING) == WRONG_ITEM_REASON


def test_a_tree_edited_mid_check_is_not_a_pass() -> None:
    reason = binding_mismatch_reason(_observations(checkout_moved=True), _BINDING)

    assert reason == MOVED_CHECKOUT_REASON


def test_an_unreadable_revision_is_not_a_pass() -> None:
    """Without a revision, nothing shows whether the tree held still."""
    reason = binding_mismatch_reason(_observations(checkout_revision=""), _BINDING)

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
    assert binding_mismatch_reason(observations, _BINDING) == INCOMPLETE_REASON


def test_a_check_this_host_never_asked_for_is_refused() -> None:
    """Extra names mean the two sides disagree about what the handoff covers."""
    observations = _observations(
        checks=[*CHECKOUT_DEPENDENT_CHECKS, "verify_something_invented"],
    )

    assert binding_mismatch_reason(observations, _BINDING) == UNRECOGNIZED_CHECK_REASON


def test_findings_pass_through_when_the_binding_holds() -> None:
    issues, advisories, unavailable = findings_from_observations(
        _observations(
            issues=[_ISSUE],
            advisories=[{
                "code": "SYMLINK_CANONICAL_HINT",
                "context": {"symlink_path": _BUDGET_PATH},
            }],
        ),
        _BINDING,
        item_ref="YOK-1",
    )

    assert [issue.code for issue in issues] == ["STALE_LINE_COUNT"]
    assert issues[0].context["path"] == _BUDGET_PATH
    assert [a["code"] for a in advisories] == ["SYMLINK_CANONICAL_HINT"]
    assert unavailable == []


def test_a_broken_binding_discards_the_findings_it_carried() -> None:
    """A stale answer's issues are as untrustworthy as its passes."""
    issues, advisories, unavailable = findings_from_observations(
        _observations(issues=[_ISSUE], checkout_moved=True),
        _BINDING,
        item_ref="YOK-1",
    )

    assert issues == []
    assert advisories == []
    assert [u.check for u in unavailable] == list(CHECKOUT_DEPENDENT_CHECKS)


def test_every_unperformed_check_names_its_cause_and_a_way_forward() -> None:
    _issues, _advisories, unavailable = findings_from_observations(
        _observations(checkout_moved=True), _BINDING, item_ref="YOK-1",
    )

    for entry in unavailable:
        assert entry.reason == MOVED_CHECKOUT_REASON
        assert entry.check in entry.recovery
        assert "YOK-1" in entry.recovery
        # Something moved; the same command run again can settle it.
        assert entry.retryable is True


def test_an_advisory_about_a_path_outside_the_file_budget_is_dropped() -> None:
    """Advisories are hints, so an ungrounded one is discarded, not escalated."""
    _issues, advisories, unavailable = findings_from_observations(
        _observations(advisories=[{
            "code": "SYMLINK_CANONICAL_HINT",
            "context": {"symlink_path": "some/other/file.py"},
        }]),
        _BINDING,
        item_ref="YOK-1",
    )

    assert advisories == []
    assert unavailable == []


def test_the_unperformed_report_carries_what_it_rejected() -> None:
    """The operator needs to see which finding could not be admitted."""
    _issues, _advisories, unavailable = findings_from_observations(
        _observations(issues=[{"code": "FILE_BUDGET_NOT_IN_CLAIM", "context": {}}]),
        _BINDING,
        item_ref="YOK-1",
    )

    assert unavailable[0].reason == UNADMISSIBLE_FINDING_REASON
    assert unavailable[0].context["rejected"][0]["code"] == "FILE_BUDGET_NOT_IN_CLAIM"

"""A concluded case run on an older commit is re-run for the merging commit."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain.qa_terminal_requirement_errors import _recovery_instruction
from yoke_core.domain.qa_terminal_settlement import blocking_requirement_issues
from runtime.api.domain.test_standalone_item_merge_commit_bound import (
    _enter_release_wait_on_close_out,  # noqa: F401 - autouse close-out stub
    _run_merge,
)
from runtime.api.domain.test_standalone_item_merge_qa import (
    EARLIER_SHA,
    MERGING_SHA,
    _item,
    _requirement,
)

CI_CONFIG = {
    "ci_workflow": "ci.yml",
    "command": "yoke watch pytest -- tests/",
    "registered_scope": "full",
}


def _ci_requirement(*, sha: str, verdict: str = "fail", **extra) -> dict:
    requirement = _requirement(verdict=verdict, sha=sha)
    requirement.update(
        {
            "method_id": "command-ci",
            "runner_id": "ci_run",
            "requirement_source": "flow_derived",
            "method_config": CI_CONFIG,
            **extra,
        }
    )
    return requirement


def _issues(requirement: dict):
    return blocking_requirement_issues(
        [requirement], accepted_shas=(MERGING_SHA,), public_ref="YOK-10", require_any=True
    )


def test_failed_run_on_older_commit_is_commit_bound():
    (issue,) = _issues(_ci_requirement(sha=EARLIER_SHA))
    assert issue.state == "stale-sha"
    assert "concluded 'failed'" in issue.detail
    assert issue.recovery == "Run `yoke qa case run --requirement-id 77`"


@pytest.mark.parametrize(
    "requirement",
    [
        _ci_requirement(sha=MERGING_SHA),
        _ci_requirement(sha=EARLIER_SHA, completed_at=None),
        _requirement(verdict="fail", sha=EARLIER_SHA),
    ],
    ids=["exact-head", "still-running", "methodless"],
)
def test_other_unfinished_runs_stay_incomplete(requirement):
    (issue,) = _issues(requirement)
    assert issue.state == "incomplete"


def test_record_verdict_is_named_only_for_a_case_that_cannot_run():
    stored_only = _ci_requirement(sha=MERGING_SHA, method_config={"command": ""})
    assert "yoke qa run record-verdict --help" in _recovery_instruction(stored_only)
    assert "record-verdict" not in _recovery_instruction(_ci_requirement(sha=""))


def test_merge_runs_the_case_for_the_new_head_after_an_older_failure(
    tmp_path: Path, monkeypatch
):
    requirement = _ci_requirement(sha=EARLIER_SHA)
    ran = []

    def run_case(requirement_id, _lane, commit_sha):
        ran.append((requirement_id, commit_sha))
        requirement.update(
            run_id=89, verdict="pass", case_outcome="passed", recorded_head_sha=commit_sha
        )

    code, merger = _run_merge(
        tmp_path,
        monkeypatch,
        _item(requirement),
        rerecord=mock.Mock(side_effect=AssertionError("not a hand verdict")),
        run_case=run_case,
    )
    assert code == 0
    assert ran == [(77, MERGING_SHA)]
    assert merger.call_args.kwargs["commit_sha"] == MERGING_SHA


def test_merge_still_refuses_a_failure_on_the_merging_commit(
    tmp_path: Path, monkeypatch
):
    run_case = mock.Mock()
    code, merger = _run_merge(
        tmp_path,
        monkeypatch,
        _item(_ci_requirement(sha=MERGING_SHA)),
        rerecord=mock.Mock(),
        run_case=run_case,
    )
    assert code == 1
    run_case.assert_not_called()
    merger.assert_not_called()

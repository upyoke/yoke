"""Re-entry resumes the covering run instead of rebasing it away.

The gate rebases before it looks for covering CI, which is right on a
candidate no run has examined and wrong on every re-entry: the rebase moves
the candidate onto an advanced base, the still-running run is force-cancelled
as superseded, and the gate pays for the same answer twice. These cases pin
the lookup ahead of the rebase, and pin that an unexamined candidate is still
rebased exactly as before.
"""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import (
    LANE_HEAD,
    ci_case,
    completed_run,
    in_flight_run,
    wire_ci_case,
)

from yoke_core.domain import (
    authored_file_merge_preflight as file_line_preflight,
    qa_case_ci_covering_run as covering_run,
    qa_case_ci_entry_run as entry_run,
    qa_case_ci_lane,
    qa_case_ci_resume,
    qa_case_ci_run,
    qa_case_ci_superseded_run,
    qa_case_execution,
)
from yoke_core.domain.qa_case_execution import QaCaseExecutionError

ADVANCED_HEAD = "c" * 40


@pytest.fixture()
def live_lane(tmp_path, monkeypatch):
    """The runner's boundaries with the lane live on its own branch."""
    checkout, recorder, artifact = wire_ci_case(tmp_path, monkeypatch)
    monkeypatch.setattr(qa_case_ci_lane, "checked_out_branch", lambda _c: "PRJ-9")
    monkeypatch.setattr(qa_case_ci_lane, "ref_sha", lambda *_a: LANE_HEAD)
    monkeypatch.setattr(
        file_line_preflight, "enforce_authored_file_limit", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        entry_run, "open_landing_pull_request", lambda *a, **k: "213",
    )
    return checkout, recorder, artifact


def _queue_project(monkeypatch, *, routed: bool = True) -> None:
    monkeypatch.setattr(entry_run, "routes_through_merge_queue", lambda _p: routed)
    monkeypatch.setattr(entry_run, "base_branch", lambda _p, _c: "main")


def _rebase_spy(monkeypatch) -> mock.Mock:
    rebase = mock.Mock()
    monkeypatch.setattr(entry_run, "rebase_lane_onto_base", rebase)
    return rebase


def _run(checkout, **kwargs):
    with mock.patch.object(
        qa_case_ci_lane,
        "dispatch_workflow",
        mock.Mock(side_effect=AssertionError("must not dispatch")),
    ):
        return qa_case_ci_run.execute_ci_case(
            ci_case(), checkout_path=checkout, **kwargs,
        )


def test_a_run_still_in_flight_keeps_the_candidate_off_the_rebase(
    live_lane, monkeypatch,
):
    """The exact re-entry incident: attach, do not rebase or supersede."""
    checkout, recorder, _ = live_lane
    _queue_project(monkeypatch)
    rebase = _rebase_spy(monkeypatch)
    cancel = mock.Mock(return_value="")
    monkeypatch.setattr(qa_case_ci_superseded_run, "force_cancel_if_rebased", cancel)
    monkeypatch.setattr(
        covering_run, "find_run_for_tree", lambda **k: in_flight_run(LANE_HEAD),
    )
    monkeypatch.setattr(
        entry_run,
        "find_entry_run",
        mock.Mock(side_effect=AssertionError("the resumed run is already known")),
    )

    with mock.patch.object(
        qa_case_ci_lane, "await_workflow", lambda **k: (0, "success"),
    ):
        result = _run(checkout)

    assert result["ci_run_source"] == covering_run.ATTACHED
    assert result["ci_run_id"] == "77"
    assert result["verdict"] == "pass"
    assert result["superseded_ci_run_id"] is None
    rebase.assert_not_called()
    cancel.assert_not_called()
    assert recorder.payload("qa.run.complete")["verdict"] == "pass"


def test_a_concluded_run_on_the_candidate_is_adopted_without_rebasing(
    live_lane, monkeypatch,
):
    checkout, _recorder, _ = live_lane
    _queue_project(monkeypatch)
    rebase = _rebase_spy(monkeypatch)
    monkeypatch.setattr(
        covering_run, "find_run_for_tree", lambda **k: completed_run(LANE_HEAD),
    )

    with mock.patch.object(
        qa_case_ci_lane,
        "await_workflow",
        mock.Mock(side_effect=AssertionError("must not await a concluded run")),
    ):
        result = _run(checkout)

    assert result["ci_run_source"] == covering_run.ADOPTED
    assert result["verdict"] == "pass"
    rebase.assert_not_called()


def test_adopted_run_upload_failure_names_same_run_recovery(
    live_lane, monkeypatch,
) -> None:
    checkout, recorder, _ = live_lane
    _queue_project(monkeypatch)
    rebase = _rebase_spy(monkeypatch)
    monkeypatch.setattr(
        covering_run, "find_run_for_tree", lambda **k: completed_run(LANE_HEAD),
    )

    def fail_artifact(function_id, requirement_id, payload, **kwargs):
        if function_id == "qa.artifact.add":
            raise QaCaseExecutionError("qa.artifact.add failed (s3_upload_failed)")
        return recorder(function_id, requirement_id, payload, **kwargs)

    monkeypatch.setattr(qa_case_execution, "_dispatch", fail_artifact)

    with pytest.raises(QaCaseExecutionError) as error:
        _run(checkout)

    message = str(error.value)
    assert "recorded QA run #77" in message
    assert "--requirement-id 41 --run-id 77" in message
    assert "yoke qa run complete" in message
    assert not any(name == "qa.run.complete" for name, _, _ in recorder.calls)
    rebase.assert_not_called()


def test_an_unexamined_candidate_is_still_rebased_before_it_is_published(
    live_lane, monkeypatch,
):
    """First entry is unchanged: no covering run means the rebase happens."""
    checkout, _recorder, _ = live_lane
    _queue_project(monkeypatch)
    rebase = _rebase_spy(monkeypatch)
    monkeypatch.setattr(covering_run, "find_run_for_tree", lambda **k: None)
    monkeypatch.setattr(
        entry_run, "find_entry_run", lambda **k: completed_run(LANE_HEAD),
    )

    result = _run(checkout)

    assert result["ci_run_source"] == covering_run.ADOPTED
    rebase.assert_called_once()


def test_a_queue_lane_only_resumes_the_pull_request_run_that_can_gate_it(
    live_lane, monkeypatch,
):
    """A dispatch run cannot satisfy a required entry check, so it is not resumed."""
    checkout, _recorder, _ = live_lane
    _queue_project(monkeypatch)
    seen: list[str] = []

    def _find(**kwargs):
        seen.append(kwargs.get("event", ""))
        return None

    monkeypatch.setattr(covering_run, "find_run_for_tree", _find)
    monkeypatch.setattr(
        entry_run, "find_entry_run", lambda **k: completed_run(LANE_HEAD),
    )
    _rebase_spy(monkeypatch)

    _run(checkout)

    assert seen == ["pull_request"]


def test_a_dispatch_lane_resumes_a_run_however_it_was_triggered(
    live_lane, monkeypatch,
):
    checkout, _recorder, _ = live_lane
    _queue_project(monkeypatch, routed=False)
    rebase = _rebase_spy(monkeypatch)
    seen: list[str] = []

    def _find(**kwargs):
        seen.append(kwargs.get("event", ""))
        return in_flight_run(LANE_HEAD)

    monkeypatch.setattr(covering_run, "find_run_for_tree", _find)

    with mock.patch.object(
        qa_case_ci_lane, "await_workflow", lambda **k: (0, "success"),
    ):
        result = _run(checkout)

    assert seen == [""]
    assert result["ci_run_source"] == covering_run.ATTACHED
    rebase.assert_not_called()


def test_an_unreachable_lookup_rebases_instead_of_failing_the_gate(
    live_lane, monkeypatch, capsys,
):
    """The same lookup runs again below, where its failure is recorded."""
    checkout, _recorder, _ = live_lane
    _queue_project(monkeypatch)
    rebase = _rebase_spy(monkeypatch)
    calls = {"n": 0}

    def _find(**_kwargs):
        calls["n"] += 1
        raise QaCaseExecutionError("could not query workflow runs: 502")

    monkeypatch.setattr(covering_run, "find_run_for_tree", _find)
    monkeypatch.setattr(
        entry_run, "find_entry_run", lambda **k: completed_run(LANE_HEAD),
    )

    result = _run(checkout)

    assert result["verdict"] == "pass"
    assert calls["n"] == 1
    rebase.assert_called_once()
    assert "could not check for a run already covering" in capsys.readouterr().err


def test_a_released_lane_never_probes_because_it_cannot_be_rebased(
    tmp_path, monkeypatch,
):
    """A recorded commit with no checkout has no head to look a run up by."""
    checkout, _recorder, _artifact = wire_ci_case(tmp_path, monkeypatch)
    _queue_project(monkeypatch)
    monkeypatch.setattr(
        qa_case_ci_lane,
        "ref_sha",
        mock.Mock(side_effect=AssertionError("must not resolve a released lane")),
    )

    prepared = qa_case_ci_resume.prepare_lane_preserving_covering_run(
        checkout,
        project="yoke",
        repo="acme/widgets",
        workflow="ci.yml",
        branch="PRJ-9",
        lane_is_checked_out=False,
        requirement_id=41,
        timeout_seconds=60,
    )

    assert prepared.resumed_run is None
    assert prepared.queue_target == "main"

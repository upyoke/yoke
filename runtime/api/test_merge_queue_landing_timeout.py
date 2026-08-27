"""What a poll-budget timeout tells the operator about its claim.

The message is the whole recovery surface for a resumable outcome, so
each claim state is covered by what the operator would have to do next:
run the command as-is, re-acquire first, or coordinate with the session
that holds it.
"""

from types import SimpleNamespace

import pytest

from runtime.api.merge_queue_landing_test_helpers import (
    HELD_BY_THIS_SESSION,
    ok_response,
)

from yoke_core.domain import merge_queue_landing_timeout as timeout_mod


RESUME = 'yoke merge item YOK-200 --result "r" --verification "v"'


def dispatch_holder(holder, *, success=True, message=""):
    def dispatch(**_kw):
        if not success:
            return SimpleNamespace(
                success=False,
                result=None,
                error=SimpleNamespace(message=message),
            )
        return ok_response({"holder": holder})

    return dispatch


def message(holder_dispatch, *, resume=RESUME, last_observed=""):
    return timeout_mod.timeout_message(
        pr_num="42",
        deadline_seconds=2700.0,
        item_id=1,
        item_ref="YOK-200",
        resume_command=resume,
        dispatch=holder_dispatch,
        last_observed=last_observed,
    )


@pytest.fixture(autouse=True)
def _this_session(monkeypatch):
    monkeypatch.setattr(
        timeout_mod,
        "_ambient_session_id",
        lambda: "sess-1",
    )


def test_held_claim_prints_a_command_that_runs_as_is():
    text = message(dispatch_holder(HELD_BY_THIS_SESSION))
    assert "still held (claim 77)" in text
    assert "nothing needs re-acquiring" in text
    assert text.endswith(RESUME)
    # The recipe that failed in the field named no re-acquire step because
    # it assumed one was never needed; a held claim must not name one now.
    assert "claims work acquire" not in text


def test_released_claim_names_the_re_acquire_step_first():
    text = message(dispatch_holder(None))
    assert "no longer held" in text
    assert "yoke claims work acquire --item YOK-200" in text
    assert text.endswith(RESUME)


def test_foreign_holder_routes_to_coordination():
    text = message(dispatch_holder({"claim_id": 9, "session_id": "other"}))
    assert "held by another session (other)" in text


def test_unreadable_claim_reports_why_and_how_to_check():
    text = message(dispatch_holder(None, success=False, message="offline"))
    assert "could not be read (offline)" in text
    assert "yoke claims work holder-get YOK-200" in text


def test_message_keeps_the_landing_resumable_and_names_the_budget():
    text = message(dispatch_holder(HELD_BY_THIS_SESSION))
    assert "did not merge within 2700s" in text
    assert "may still merge it" in text


def test_the_final_reading_is_stated_so_a_doomed_wait_is_not_re_run():
    """Whether resuming is even the right move depends on this reading."""
    text = message(
        dispatch_holder(HELD_BY_THIS_SESSION),
        last_observed=(
            "pull request 42: merged=false, state=open, "
            "merge-when-ready=armed, queue-entry=absent, train-run=failure"
        ),
    )
    assert "last observed" in text
    assert "queue-entry=absent" in text
    assert "train-run=failure" in text
    assert text.endswith(RESUME)


def test_a_poll_that_read_nothing_conclusive_says_that_rather_than_nothing():
    text = message(dispatch_holder(HELD_BY_THIS_SESSION))
    assert "read nothing conclusive" in text


def test_missing_caller_command_falls_back_rather_than_inventing_one():
    text = message(dispatch_holder(HELD_BY_THIS_SESSION), resume="")
    assert text.endswith(timeout_mod.GENERIC_RESUME)


def test_resume_command_reproduces_the_evidence_flags():
    args = SimpleNamespace(
        project="",
        target="",
        result="did the thing",
        verification="suite green",
        verification_status="passed",
        no_changes=False,
        skip_status=False,
        pr=False,
        json=True,
    )
    command = timeout_mod.merge_item_resume_command("YOK-200", args)
    assert command == (
        "yoke merge item YOK-200 --result 'did the thing' "
        "--verification 'suite green' --json"
    )


def test_resume_command_carries_non_default_and_flag_arguments():
    args = SimpleNamespace(
        project="yoke",
        target="release",
        result="",
        verification="",
        verification_status="failed",
        no_changes=True,
        skip_status=True,
        pr=True,
        wait=True,
        json=False,
    )
    command = timeout_mod.merge_item_resume_command("YOK-200", args)
    assert command == (
        "yoke merge item YOK-200 --project yoke --target release "
        "--verification-status failed --no-changes --skip-status --pr --wait"
    )

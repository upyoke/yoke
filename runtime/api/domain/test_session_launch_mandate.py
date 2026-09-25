"""Server-composed single-item launch mandate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from yoke_contracts.session_control.models import LaunchCreateRequest
from yoke_core.domain.session_launch_mandate import (
    compose_item_launch_instructions,
    compose_single_item_mandate,
)
from yoke_core.domain.release_wait_ownership import (
    RELEASE_WAIT_RETENTION_TEACHING,
)
from yoke_core.domain.session_launch_mandate_teaching import (
    CANDIDATE_REVIEW_TEACHING,
    COMMITTED_GATE_TEACHING,
    HEADLESS_TOOL_CONTINUATION_TEACHING,
)
from yoke_core.domain.session_launch_types import SessionLaunchError


def _stub_route(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_mandate._route_for_item",
        lambda *_args, **_kwargs: (
            "/yoke dash YOK-12",
            "the Dash leg to its merge/evidence close",
        ),
    )


def _mandate(*, extras: str = "") -> str:
    return compose_single_item_mandate(
        public_ref="YOK-12",
        entrypoint="/yoke dash YOK-12",
        remaining_legs="the Dash leg to its merge/evidence close",
        extras=extras,
    )


def test_composed_mandate_names_item_entrypoint_and_the_routed_legs() -> None:
    body = _mandate()
    assert body.startswith("/yoke dash YOK-12\n")
    assert "acquire the YOK-12 work claim" in body
    assert "the Dash leg to its merge/evidence close" in body
    assert "do not chain into other items" in body
    assert "NEVER send progress: no percentages" in body


def test_composed_mandate_tells_workers_to_leave_the_only_push_to_the_gate() -> None:
    body = _mandate()
    assert COMMITTED_GATE_TEACHING in body
    assert "rebases onto the base branch, pushes once, and runs CI" in body
    assert "do not push the lane by hand" in body


def test_composed_mandate_names_the_candidate_review_a_merge_can_refuse() -> None:
    body = _mandate()
    assert CANDIDATE_REVIEW_TEACHING in body
    assert "merge_candidate_review" in CANDIDATE_REVIEW_TEACHING
    assert "refuses an uncleared candidate by name" in CANDIDATE_REVIEW_TEACHING
    assert "a blocker, not a retry" in CANDIDATE_REVIEW_TEACHING
    assert "needs its own review" in CANDIDATE_REVIEW_TEACHING


def test_the_candidate_review_precedes_the_merge_wait_teaching() -> None:
    """A worker learns the merge can refuse before it learns how to wait."""
    body = _mandate()
    assert body.index(CANDIDATE_REVIEW_TEACHING) < body.index(
        "headless command that cannot be prompted again"
    )


def test_composed_mandate_tells_workers_to_continue_a_handed_back_call() -> None:
    body = _mandate()
    assert HEADLESS_TOOL_CONTINUATION_TEACHING in body
    teaching = HEADLESS_TOOL_CONTINUATION_TEACHING
    assert "A tool call that outlives its yield is still running" in teaching
    assert "moves a long command to a background task" in teaching
    assert "hands back a continuation handle" in teaching
    assert "not an interruption" in teaching
    assert "Continue that same call through your harness's continuation" in teaching
    assert "reading the background task's output continues the call" in teaching
    assert "only ending the turn kills the watcher" in teaching
    assert "Never start a second invocation beside a live one" in teaching
    # Sanctioned early stops stay named: landing handoff, plus the taught
    # local-check interrupt on a project with declared CI.
    assert "a merge that returned landing_pending has its landing notice" in teaching
    assert (
        "when a *local* test check on a project with declared CI has already "
        "exceeded about one minute" in teaching
    )
    assert "a machine-specific diagnostic" in teaching
    assert "a project without CI" in teaching


def test_composed_mandate_keeps_a_release_wait_owner_holding_its_item() -> None:
    """The close it carries says report and END when the legs are complete,
    and a merge that stopped at a release wait has not completed them."""
    body = _mandate()
    assert RELEASE_WAIT_RETENTION_TEACHING in body
    teaching = RELEASE_WAIT_RETENTION_TEACHING
    assert "completed merge that is NOT a finished item" in teaching
    assert "keeps your work claim and parks your session" in teaching
    assert "Do NOT release the claim and do NOT end your session" in teaching
    assert "deployment wake re-enters you" in teaching
    assert "no run QA or run approval closes" in teaching
    assert (
        "accepted or explicitly discharged by `post_deploy_no_obligation`" in teaching
    )
    assert "even while sibling QA holds the run open" in teaching
    assert "run QA or run approval holds every member" in teaching
    assert "all item gates and shared gates pass and the run succeeds" in teaching
    assert "Do not re-run merge solely for that acceptance" in teaching
    assert "automatic close-out could not finish" in teaching
    assert "Only once the item reaches done do you send the DONE report" in teaching
    assert "active work claim protects the session" in teaching


def test_the_done_report_step_names_the_release_wait_as_incomplete() -> None:
    body = _mandate()
    assert "Complete means the item reached its own terminal status" in body
    assert "stopped at a pinned release wait has NOT completed those legs" in body


def test_the_retention_rule_precedes_the_landing_handoff() -> None:
    """Order is the teaching: what "complete" means, before the two waits a
    worker may legitimately stop on."""
    body = _mandate()
    assert body.index(RELEASE_WAIT_RETENTION_TEACHING) < body.index(
        "headless command that cannot be prompted again"
    )


def test_the_landing_handoff_precedes_the_continuation_rule() -> None:
    """Order is the teaching: stop only where the command handed the wait off."""
    body = _mandate()
    landing = body.index("headless command that cannot be prompted again")
    assert landing < body.index(HEADLESS_TOOL_CONTINUATION_TEACHING)


def test_worker_sends_its_done_deliberately_before_releasing() -> None:
    body = _mandate()
    assert "Ending a turn sends no Fleet message" in body
    assert (
        'printf %s "DONE YOK-12 <one-line summary>" | yoke say --stdin --steering'
        in body
    )
    assert "before releasing any claim you still hold" in body
    assert "the item you last held in this session" in body
    assert "The PREFIX-N in the DONE heading is the report identity" in body
    assert "END your session" in body


def test_composed_mandate_embeds_no_session_id() -> None:
    """The address must survive the seat that launched the worker ending."""
    body = _mandate()
    assert "--session " not in body
    assert "steerer-session" not in body


def test_extras_append_after_the_canonical_mandate() -> None:
    body = _mandate(extras="Also reopen the failed QA case.")
    mandate, extras = body.split("\n\nAlso reopen", 1)
    assert "/yoke dash YOK-12" in mandate
    assert "yoke say --stdin --steering" in mandate
    assert extras.startswith(" the failed QA case.")


def test_composed_create_uses_live_route_and_appends_extras(monkeypatch) -> None:
    _stub_route(monkeypatch)
    parsed = LaunchCreateRequest(
        project="yoke",
        executor_surface="cursor-cli",
        item="YOK-12",
        instructions="Also reopen the failed QA case.",
        idempotency_key="compose-1",
    )
    body = compose_item_launch_instructions(SimpleNamespace(), parsed, 1)
    assert body.startswith("/yoke dash YOK-12\n")
    assert "acquire the YOK-12 work claim" in body
    assert "yoke say --stdin --steering" in body
    assert body.endswith("Also reopen the failed QA case.")


def test_raw_instructions_keep_an_explicit_full_body() -> None:
    parsed = LaunchCreateRequest(
        project="yoke",
        executor_surface="cursor-cli",
        item="YOK-12",
        instructions="Custom full body.",
        compose_mandate=False,
        idempotency_key="raw-1",
    )
    body = compose_item_launch_instructions(SimpleNamespace(), parsed, 1)
    assert body == "Custom full body."


def test_itemless_raw_instructions_keep_an_explicit_full_body() -> None:
    parsed = LaunchCreateRequest(
        project="yoke",
        executor_surface="cursor-cli",
        instructions="Custom full body.",
        compose_mandate=False,
        idempotency_key="raw-itemless",
    )
    assert parsed.item is None
    body = compose_item_launch_instructions(SimpleNamespace(), parsed, 1)
    assert body == "Custom full body."


def test_composed_create_without_item_is_refused() -> None:
    with pytest.raises(ValidationError):
        LaunchCreateRequest(
            project="yoke",
            executor_surface="cursor-cli",
            idempotency_key="composed-missing",
        )


def test_itemless_raw_without_body_is_refused() -> None:
    with pytest.raises(ValidationError):
        LaunchCreateRequest(
            project="yoke",
            executor_surface="cursor-cli",
            compose_mandate=False,
            instructions="  ",
            idempotency_key="raw-empty-itemless",
        )


def test_raw_instructions_refuse_an_empty_body() -> None:
    with pytest.raises(ValidationError):
        LaunchCreateRequest(
            project="yoke",
            executor_surface="cursor-cli",
            item="YOK-12",
            instructions="  ",
            compose_mandate=False,
            idempotency_key="raw-empty",
        )


def test_unroutable_live_step_refuses_composition(monkeypatch) -> None:
    from yoke_core.domain import session_launch_mandate as mandate

    monkeypatch.setattr(mandate, "resolve_item_id", lambda *_a, **_k: 12)
    monkeypatch.setattr(
        mandate, "load_item_workflow_runtime", lambda *_a, **_k: object()
    )
    monkeypatch.setattr(mandate, "live_next_step", lambda *_a, **_k: "wait")
    monkeypatch.setattr(mandate, "marker", lambda _conn: "%s")
    conn = SimpleNamespace(
        execute=lambda *_a, **_k: SimpleNamespace(
            fetchone=lambda: {"status": "implementing"}
        )
    )
    with pytest.raises(SessionLaunchError) as raised:
        mandate._route_for_item(conn, "YOK-12", 1)
    assert raised.value.code == "mandate_unroutable"

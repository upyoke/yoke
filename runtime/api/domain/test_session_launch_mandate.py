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
    LEVEL_HANDOFF_TEACHING,
    CANDIDATE_REVIEW_TEACHING,
    COMMITTED_GATE_TEACHING,
    HEADLESS_TOOL_CONTINUATION_TEACHING,
    PROGRESS_CHECKPOINT_TEACHING,
)
from yoke_core.domain.session_launch_types import SessionLaunchError


def _stub_route(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_mandate.resolve_item_ref_or_none",
        lambda *_args, **_kwargs: 12,
    )
    monkeypatch.setattr(
        "yoke_core.domain.workflow_execution_instructions.resolve_for_item",
        lambda *_args, **_kwargs: [],
    )
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


def test_composed_launch_delivers_full_item_instructions(monkeypatch):
    _stub_route(monkeypatch)
    monkeypatch.setattr(
        "yoke_core.domain.workflow_execution_instructions.resolve_for_item",
        lambda conn, item_id: [{"id": 7, "content": "Required operator instruction"}],
    )
    parsed = LaunchCreateRequest(
        project="yoke", executor_surface="cursor-cli", item="YOK-12",
        compose_mandate=True, instructions="", idempotency_key="instruction-launch",
    )
    body = compose_item_launch_instructions(SimpleNamespace(), parsed, 1)
    assert body.startswith("Operator execution instructions (obey these):\nRequired operator instruction")
    assert body.count("Required operator instruction") == 1
    assert "acquire the YOK-12 work claim" in body


def test_composed_mandate_claims_first_then_follows_the_live_bound_skill() -> None:
    body = _mandate()
    assert body.startswith("/yoke dash YOK-12\n")
    assert "acquire the YOK-12 work claim" in body
    assert 'yoke claims work acquire --item YOK-12 --reason "<why you are claiming it>"' in body
    assert "the Dash leg to its merge/evidence close" in body
    assert body.index("as your FIRST action") < body.index("next live bound skill")
    assert "read its phase instructions before verification, merge or delivery" in body
    assert "Do NOT create or dispatch any deployment run" in body


def test_composed_mandate_keeps_the_item_resumable() -> None:
    body = _mandate()
    assert "read the Progress Log and lane status/log" in body
    assert "preserve existing work" in body
    assert "Before stopping short of done, append a Progress Log checkpoint" in body
    assert "stage, committed and dirty work, and next action" in body
    assert "If your claim is swept, reacquire and continue" in body


def test_the_level_handoff_steps_are_inline_not_a_pointer_to_a_doc() -> None:
    body = _mandate()
    assert LEVEL_HANDOFF_TEACHING in body
    teaching = LEVEL_HANDOFF_TEACHING
    steps = [
        "handoff with reason level_change",
        "takes precedence over retaining a release wait",
        "(1) append a Progress Log checkpoint",
        "yoke items progress-log append PREFIX-N",
        "(2) release every claim you hold with `yoke claims work release --all-mine",
        "(3) run the handoff's next_command exactly as returned",
        "a refusal names its recovery",
        "(4) verify the launch was accepted with `yoke session-control launch get",
        "then end your session",
    ]
    positions = [teaching.index(step) for step in steps]
    assert positions == sorted(positions)
    # Older installed layers lack the section a pointer would name.
    assert "session-level-routing" not in teaching
    assert "Stage-level handoff" not in teaching


def test_the_level_handoff_precedes_the_release_wait_it_overrides() -> None:
    body = _mandate()
    assert body.index(LEVEL_HANDOFF_TEACHING) < body.index(
        "A release wait retains the claim and park"
    )


def test_a_successor_reads_the_checkpoint_before_any_gate_or_merge() -> None:
    body = _mandate()
    assert body.index("read the Progress Log and lane status/log") < body.index(
        LEVEL_HANDOFF_TEACHING
    )


def test_composed_mandate_delivers_operation_depth_when_the_skill_is_read() -> None:
    body = _mandate()
    assert "read its phase instructions before verification, merge or delivery" in body
    for teaching in (CANDIDATE_REVIEW_TEACHING, COMMITTED_GATE_TEACHING,
                     HEADLESS_TOOL_CONTINUATION_TEACHING, PROGRESS_CHECKPOINT_TEACHING,
                     RELEASE_WAIT_RETENTION_TEACHING):
        assert teaching not in body


def test_composed_mandate_reports_substantive_facts_and_closes_only_at_terminal() -> None:
    body = _mandate()
    assert "failures, blockers, conflicts, outside-scope defects or decisions" in body
    assert "Keep progress in your own output" in body
    assert "Only at the item's terminal status" in body
    assert "A release wait retains the claim and park" in body
    assert "it owes no DONE or END" in body
    assert 'printf %s "DONE YOK-12 <one-line summary>" | yoke say --stdin --steering' in body
    assert "before releasing a claim you still hold, then END your session" in body
    assert "Ending a turn sends no Fleet message" in body


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

    monkeypatch.setattr(mandate, "resolve_item_ref_or_none", lambda *_a, **_k: 12)
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

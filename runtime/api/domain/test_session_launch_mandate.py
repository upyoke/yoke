"""Server-composed single-item launch mandate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_contracts.session_control.models import LaunchCreateRequest
from yoke_core.domain.session_launch_mandate import (
    COMMITTED_GATE_TEACHING,
    compose_item_launch_instructions,
    compose_single_item_mandate,
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


def test_worker_sends_its_done_deliberately_before_releasing() -> None:
    body = _mandate()
    assert "Ending a turn sends no Fleet message" in body
    assert (
        'printf %s "DONE YOK-12 <one-line summary>" | yoke say --stdin --steering'
        in body
    )
    assert "before releasing any claim you still hold" in body
    assert "the item you last held in this session" in body
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


def test_raw_instructions_refuse_an_empty_body() -> None:
    parsed = LaunchCreateRequest(
        project="yoke",
        executor_surface="cursor-cli",
        item="YOK-12",
        instructions="  ",
        compose_mandate=False,
        idempotency_key="raw-empty",
    )
    with pytest.raises(SessionLaunchError) as raised:
        compose_item_launch_instructions(SimpleNamespace(), parsed, 1)
    assert raised.value.code == "payload_invalid"


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

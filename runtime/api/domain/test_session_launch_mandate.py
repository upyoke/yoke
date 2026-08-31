"""Server-composed single-item launch mandate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.session_control.models import LaunchCreateRequest
from yoke_core.domain.session_launch_mandate import (
    compose_item_launch_instructions,
    compose_single_item_mandate,
)
from yoke_core.domain.session_launch_types import SessionLaunchError


def _create_request(**payload: object) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="session_control.launch.create",
        actor=ActorContext(actor_id="2", session_id="steerer-session"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_composed_mandate_names_item_entrypoint_and_done_target() -> None:
    body = compose_single_item_mandate(
        public_ref="YOK-12",
        entrypoint="/yoke dash YOK-12",
        remaining_legs="the Dash leg to its merge/evidence close",
        done_session_id="steerer-session",
    )
    assert body.startswith("/yoke dash YOK-12\n")
    assert "acquire the YOK-12 work claim" in body
    assert "the Dash leg to its merge/evidence close" in body
    assert "yoke say --stdin --session steerer-session" in body
    assert "DONE YOK-12" in body
    assert "do not chain into other items" in body
    assert "NEVER send progress: no percentages" in body


def test_extras_append_after_the_canonical_mandate() -> None:
    body = compose_single_item_mandate(
        public_ref="YOK-12",
        entrypoint="/yoke dash YOK-12",
        remaining_legs="the Dash leg to its merge/evidence close",
        done_session_id="steerer-session",
        extras="Also reopen the failed QA case.",
    )
    mandate, extras = body.split("\n\nAlso reopen", 1)
    assert "/yoke dash YOK-12" in mandate
    assert extras.startswith(" the failed QA case.")


def test_composed_create_uses_live_route_and_appends_extras(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_mandate._route_for_item",
        lambda *_args, **_kwargs: (
            "/yoke dash YOK-12",
            "the Dash leg to its merge/evidence close",
        ),
    )
    parsed = LaunchCreateRequest(
        project="yoke",
        executor_surface="cursor-cli",
        item="YOK-12",
        instructions="Also reopen the failed QA case.",
        idempotency_key="compose-1",
    )
    body = compose_item_launch_instructions(
        SimpleNamespace(),
        parsed,
        _create_request(),
        1,
    )
    assert body.startswith("/yoke dash YOK-12\n")
    assert "acquire the YOK-12 work claim" in body
    assert "steerer-session" in body
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
    body = compose_item_launch_instructions(
        SimpleNamespace(),
        parsed,
        _create_request(),
        1,
    )
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
        compose_item_launch_instructions(
            SimpleNamespace(),
            parsed,
            _create_request(),
            1,
        )
    assert raised.value.code == "payload_invalid"


def test_composed_create_refuses_a_missing_creator_session() -> None:
    parsed = LaunchCreateRequest(
        project="yoke",
        executor_surface="cursor-cli",
        item="YOK-12",
        idempotency_key="no-session",
    )
    request = FunctionCallRequest(
        function="session_control.launch.create",
        actor=ActorContext(actor_id="2", session_id=""),
        target=TargetRef(kind="global"),
        payload={},
    )
    with pytest.raises(SessionLaunchError) as raised:
        compose_item_launch_instructions(SimpleNamespace(), parsed, request, 1)
    assert raised.value.code == "creator_session_required"


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

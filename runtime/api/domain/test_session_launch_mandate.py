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


def test_composed_launch_omits_item_instructions(monkeypatch):
    _stub_route(monkeypatch)
    monkeypatch.setattr(
        "yoke_core.domain.workflow_execution_instructions.resolve_for_item",
        lambda conn, item_id: [{"id": 7, "content": "Required operator instruction"}],
    )
    parsed = LaunchCreateRequest(
        project="yoke",
        executor_surface="cursor-cli",
        item="YOK-12",
        compose_mandate=True,
        instructions="",
        idempotency_key="instruction-launch",
    )
    body = compose_item_launch_instructions(SimpleNamespace(), parsed, 1)
    assert "Required operator instruction" not in body


def test_composed_mandate_leads_with_the_entrypoint_and_names_the_legs() -> None:
    body = _mandate()
    assert body.startswith("/yoke dash YOK-12\n")
    assert "the Dash leg to its merge/evidence close" in body


def test_composed_mandate_delivers_operation_depth_when_the_skill_is_read() -> None:
    body = _mandate()
    for teaching in (
        CANDIDATE_REVIEW_TEACHING,
        COMMITTED_GATE_TEACHING,
        HEADLESS_TOOL_CONTINUATION_TEACHING,
        PROGRESS_CHECKPOINT_TEACHING,
        RELEASE_WAIT_RETENTION_TEACHING,
    ):
        assert teaching not in body


def test_composed_mandate_embeds_no_session_id() -> None:
    """The address must survive the seat that launched the worker ending."""
    body = _mandate()
    assert "--session " not in body
    assert "steerer-session" not in body


def test_extras_append_after_the_canonical_mandate() -> None:
    body = _mandate(extras="Also reopen the failed QA case.")
    mandate, extras = body.split("\n\nAlso reopen", 1)
    assert "/yoke dash YOK-12" in mandate
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

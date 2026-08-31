"""Launch origin is derived from a live steering claim, not caller input."""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGIN_OPERATOR,
    LAUNCH_ORIGIN_STEERING,
    LAUNCH_ORIGINS,
)
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_types import LaunchAuthorization, LaunchRequest
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    add_steering_claim,
    authorization,
    launch_connection,
)


def _create(conn, *, auth=None, key: str = "origin-key"):
    if conn.execute("SELECT 1 FROM session_relays LIMIT 1").fetchone() is None:
        add_relay(conn)
    return create_launch(
        conn,
        auth=auth or authorization(),
        request=LaunchRequest(
            project_id=10,
            executor_surface="codex-cli",
            instructions="Inspect the current work and report evidence.",
            idempotency_key=key,
            model="gpt-5",
        ),
        now=NOW,
    )


def test_vocabulary_is_exactly_operator_and_steering() -> None:
    assert LAUNCH_ORIGINS == (LAUNCH_ORIGIN_OPERATOR, LAUNCH_ORIGIN_STEERING)


def test_create_records_operator_without_a_steering_claim() -> None:
    launch = _create(launch_connection()).launch

    assert launch.origin == LAUNCH_ORIGIN_OPERATOR


def test_create_records_steering_when_the_caller_holds_the_project_seat() -> None:
    conn = launch_connection()
    add_steering_claim(conn)

    launch = _create(conn).launch

    assert launch.origin == LAUNCH_ORIGIN_STEERING


def test_create_records_operator_when_the_steering_claim_is_released() -> None:
    conn = launch_connection()
    add_steering_claim(conn, released_at=NOW)

    launch = _create(conn).launch

    assert launch.origin == LAUNCH_ORIGIN_OPERATOR


def test_create_records_operator_when_steering_claim_is_for_another_project() -> None:
    conn = launch_connection()
    add_steering_claim(conn, project_id=99)

    launch = _create(conn).launch

    assert launch.origin == LAUNCH_ORIGIN_OPERATOR


def test_create_records_operator_when_caller_session_is_absent() -> None:
    conn = launch_connection()
    add_steering_claim(conn)
    auth = LaunchAuthorization(actor_id=1, session_id=None, can_operate_project=True)

    launch = _create(conn, auth=auth).launch

    assert launch.origin == LAUNCH_ORIGIN_OPERATOR


def test_launch_request_rejects_a_caller_set_origin() -> None:
    with pytest.raises(TypeError):
        LaunchRequest(
            project_id=10,
            executor_surface="codex-cli",
            instructions="x",
            idempotency_key="k",
            origin="steering",
        )


def test_dedupe_does_not_treat_origin_as_request_identity() -> None:
    conn = launch_connection()
    first = _create(conn)
    add_steering_claim(conn)
    second = _create(conn)

    assert second.deduplicated is True
    assert second.launch.launch_id == first.launch.launch_id
    assert second.launch.origin == LAUNCH_ORIGIN_OPERATOR

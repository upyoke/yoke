"""A steering report pull reuses a schedule pass a few seconds old."""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import (
    NOW,
    PROJECT_ID,
    STEERING_SESSION,
    seed_steering_scope,
)
from yoke_core.domain import steering_fleet_report_schedule_cache as cache
from yoke_core.domain.steering_fleet_report_compose import compose_held_reports


@pytest.fixture
def steering_scope(test_db):
    cache.forget_reused_schedules()
    yield seed_steering_scope(test_db)
    cache.forget_reused_schedules()


@pytest.fixture
def passes(monkeypatch) -> list[tuple[int, str]]:
    calls: list[tuple[int, str]] = []
    compute = cache.scope_work

    def counted(conn, *, project_id, session_id):
        calls.append((project_id, session_id))
        return compute(conn, project_id=project_id, session_id=session_id)

    monkeypatch.setattr(cache, "scope_work", counted)
    return calls


def test_pulls_inside_the_window_share_one_schedule_pass(steering_scope, passes):
    first = compose_held_reports(
        steering_scope, session_id=STEERING_SESSION, now=NOW, reuse_schedule=True
    )
    second = compose_held_reports(
        steering_scope, session_id=STEERING_SESSION, now=NOW, reuse_schedule=True
    )

    assert passes == [(PROJECT_ID, STEERING_SESSION)]
    assert first.sections[0].report.available == second.sections[0].report.available


def test_an_expired_pass_is_recomputed(steering_scope, passes, monkeypatch):
    clock = [1_000.0]
    monkeypatch.setattr(cache, "monotonic", lambda: clock[0])
    cache.reused_scope_work(
        steering_scope, project_id=PROJECT_ID, session_id=STEERING_SESSION
    )
    clock[0] += cache.SCHEDULE_CACHE_SECONDS - 1
    cache.reused_scope_work(
        steering_scope, project_id=PROJECT_ID, session_id=STEERING_SESSION
    )
    clock[0] += 2
    cache.reused_scope_work(
        steering_scope, project_id=PROJECT_ID, session_id=STEERING_SESSION
    )

    assert len(passes) == 2


def test_each_session_gets_its_own_pass(steering_scope, passes):
    for session_id in (STEERING_SESSION, "another-steering-seat"):
        cache.reused_scope_work(
            steering_scope, project_id=PROJECT_ID, session_id=session_id
        )

    assert passes == [
        (PROJECT_ID, STEERING_SESSION),
        (PROJECT_ID, "another-steering-seat"),
    ]


def test_reports_that_do_not_ask_read_the_schedule_live(steering_scope, passes):
    for _ in range(2):
        compose_held_reports(steering_scope, session_id=STEERING_SESSION, now=NOW)

    assert passes == []


def test_a_connection_without_an_authority_never_shares(steering_scope, passes):
    class _Anonymous:
        info = None

        def __getattr__(self, name):
            return getattr(steering_scope, name)

    for _ in range(2):
        cache.reused_scope_work(
            _Anonymous(), project_id=PROJECT_ID, session_id=STEERING_SESSION
        )

    assert len(passes) == 2

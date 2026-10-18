"""Health HTTP reads stay independent of refresh latency and worker admission."""

import asyncio
import threading
from unittest import mock

import yoke_core.api.main  # noqa: F401 — constructs routes in production order
from yoke_core.api.routes import items_health
from yoke_core.api.health_refresh import health_refresh_lifespan


def test_unprobed_health_fails_closed_without_io():
    with mock.patch.object(items_health._main, "get_db_readonly") as connect:
        payload = asyncio.run(items_health.health())
    connect.assert_not_called()
    assert payload.migrations_current is False
    assert payload.schema_ready is False
    assert payload.can_serve_this_database is False
    assert "health_snapshot_pending" in payload.migration_content_mismatches[0]


def test_refresh_failure_preserves_last_complete_answer(caplog):
    previous = (True, [], [], [], True, True, [], [])
    items_health._snapshot = previous
    with mock.patch.object(
        items_health._main, "get_db_readonly", side_effect=OSError("private DSN")
    ):
        items_health.refresh_health_snapshot()
    assert items_health._health_snapshot() is previous
    assert "health_snapshot_refresh_failed" in caplog.text
    assert "private DSN" not in caplog.text


def test_worker_refreshes_without_requests_and_stops(monkeypatch):
    first = threading.Event()
    second = threading.Event()
    calls = []

    def refresh():
        calls.append(threading.current_thread())
        (first if len(calls) == 1 else second).set()

    monkeypatch.setattr(items_health, "refresh_health_snapshot", refresh)
    monkeypatch.setattr(
        "yoke_core.api.health_refresh.runtime_settings.get_seconds", lambda *_: 0.01
    )
    with health_refresh_lifespan():
        assert first.wait(1)
        assert second.wait(1)
        assert calls[0] is not threading.current_thread()
    assert not calls[0].is_alive()


def test_health_returns_previous_answer_while_refresh_is_blocked(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    previous = (True, [], [], [], True, True, [], [])
    items_health._snapshot = previous

    def blocked_refresh():
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(items_health, "refresh_health_snapshot", blocked_refresh)
    with health_refresh_lifespan():
        try:
            assert entered.wait(1)
            assert asyncio.run(items_health.health()).schema_ready is True
        finally:
            release.set()


def test_metadata_is_read_once_at_startup(monkeypatch):
    monkeypatch.setattr(items_health, "refresh_health_snapshot", lambda: None)
    with (
        mock.patch.object(
            items_health, "advertised_engine_version", return_value="3.2.1"
        ) as version,
        mock.patch.object(
            items_health,
            "current_github_app_public_advertisement",
            return_value=items_health.GitHubAppUnavailable(),
        ) as app,
        health_refresh_lifespan(),
    ):
        for _ in range(5):
            assert asyncio.run(items_health.health()).engine_version == "3.2.1"
        version.assert_called_once()
        app.assert_called_once()


def test_health_route_has_no_threadpool_admission_dependency():
    from fastapi.routing import APIRoute

    health = next(
        route
        for route in yoke_core.api.main.app.routes
        if isinstance(route, APIRoute) and route.path == "/v1/health"
    )
    assert asyncio.iscoroutinefunction(health.endpoint)
    assert health.dependant.dependencies == []

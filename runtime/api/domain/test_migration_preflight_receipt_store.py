"""Reading fleet rehearsal coverage from the environment that owns it."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import migration_preflight_receipt as receipt
from yoke_core.domain import migration_preflight_receipt_store as store


def _response(values, *, success: bool = True, error: str = ""):
    return SimpleNamespace(
        success=success,
        result={"values": values} if values is not None else {},
        error=None if not error else SimpleNamespace(message=error),
    )


def _patched_dispatcher(monkeypatch, response, calls=None):
    def call_dispatcher(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        call_dispatcher,
    )


def test_the_read_asks_the_registered_environment_settings_projection(monkeypatch):
    calls: list[dict] = []
    _patched_dispatcher(monkeypatch, _response({}), calls)

    store.read_coverage(
        project="yoke",
        environment="prod-db-admin",
        paths=[receipt.entry_coverage_path("0001_a")],
    )

    assert calls[0]["function_id"] == store.COVERAGE_FUNCTION_ID
    # The admin connection names a cluster; coverage is keyed by environment.
    assert calls[0]["payload"] == {
        "project": "yoke",
        "environment": "prod",
        "paths": [receipt.entry_coverage_path("0001_a")],
    }


def test_one_function_id_serves_both_the_local_and_the_relayed_authority():
    # The transport is chosen by the active connection, not by the caller, so
    # a gate on a hosted runner and a gate beside a local database cannot
    # disagree about what was rehearsed.
    assert store.COVERAGE_FUNCTION_ID == "projects.environment_settings.get"


def test_recorded_leaves_come_back_as_coverage(monkeypatch):
    path = receipt.entry_coverage_path("0001_a")
    _patched_dispatcher(monkeypatch, _response({path: "20260101T000000Z"}))

    values, unreadable = store.read_coverage(
        project="yoke", environment="prod", paths=[path]
    )

    assert unreadable == ""
    assert receipt.uncovered(["0001_a"], values) == ()


def test_a_refused_read_is_reported_rather_than_returned_empty(monkeypatch):
    # Empty would read as "unrehearsed", which is a different fact and one a
    # later retry would clear. A refusal has to survive as a refusal.
    _patched_dispatcher(
        monkeypatch, _response(None, success=False, error="permission_denied")
    )

    values, unreadable = store.read_coverage(
        project="yoke", environment="prod", paths=["a.b"]
    )

    assert values == {}
    assert "permission_denied" in unreadable


def test_a_transport_failure_is_reported_rather_than_returned_empty(monkeypatch):
    _patched_dispatcher(monkeypatch, RuntimeError("connection refused"))

    values, unreadable = store.read_coverage(
        project="yoke", environment="prod", paths=["a.b"]
    )

    assert values == {}
    assert "connection refused" in unreadable


def test_a_response_without_values_is_unreadable_rather_than_uncovered(monkeypatch):
    _patched_dispatcher(monkeypatch, _response(None))

    values, unreadable = store.read_coverage(
        project="yoke", environment="prod", paths=["a.b"]
    )

    assert values == {}
    assert unreadable


def test_asking_for_nothing_reads_nothing_rather_than_calling_the_surface(
    monkeypatch,
):
    def refuse(**_kwargs):
        raise AssertionError("no paths means no question to ask")

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        refuse,
    )

    assert store.read_coverage(project="yoke", environment="prod", paths=[]) == ({}, "")

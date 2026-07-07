"""Live-schema probe regressions for schema_api_context."""

from __future__ import annotations

import pytest

from yoke_core.domain import schema_api_context as sac


def test_live_schema_probe_falls_back_after_connect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_connect():
        calls.append("connect")
        raise TimeoutError("simulated unavailable live schema")

    monkeypatch.setattr(sac, "_LIVE_SCHEMA_CACHE", {})
    monkeypatch.setattr(sac, "_LIVE_SCHEMA_UNAVAILABLE", False)
    monkeypatch.setattr(sac, "_connect_live_schema", fake_connect)

    assert sac._try_live_schema("items") is None
    assert sac._try_live_schema("harness_sessions") is None
    assert calls == ["connect"]


def test_live_schema_probe_caches_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeConn:
        def close(self) -> None:
            pass

    def fake_connect() -> FakeConn:
        calls.append("connect")
        return FakeConn()

    def fake_columns(conn, table: str) -> list[tuple[str, str]]:
        assert isinstance(conn, FakeConn)
        return [("id", "integer"), (f"{table}_marker", "text")]

    monkeypatch.setattr(sac, "_LIVE_SCHEMA_CACHE", {})
    monkeypatch.setattr(sac, "_LIVE_SCHEMA_UNAVAILABLE", False)
    monkeypatch.setattr(sac, "_connect_live_schema", fake_connect)
    monkeypatch.setattr(sac, "_get_columns_with_types", fake_columns)

    assert sac._try_live_schema("items") == [
        ("id", "integer"),
        ("items_marker", "text"),
    ]
    assert sac._try_live_schema("items") == [
        ("id", "integer"),
        ("items_marker", "text"),
    ]
    assert calls == ["connect"]

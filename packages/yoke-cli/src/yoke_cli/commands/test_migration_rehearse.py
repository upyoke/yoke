"""Tests for the source-dev/admin migration rehearsal wrapper."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_cli.commands import migration_rehearse as subject


def test_https_connection_is_refused_before_import(monkeypatch, capsys) -> None:
    monkeypatch.setattr(subject, "local_authority_is_pinned", lambda: False)
    monkeypatch.setattr(
        subject.machine_config,
        "active_connection",
        lambda **_kwargs: {"transport": "https"},
    )
    monkeypatch.setattr(
        subject.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(AssertionError("must not import")),
    )

    assert subject.migration_rehearse(["YOK-1"]) == 1
    assert "not relayed over HTTPS" in capsys.readouterr().err


def test_local_connection_delegates_to_installed_runtime(monkeypatch) -> None:
    monkeypatch.setattr(subject, "local_authority_is_pinned", lambda: False)
    monkeypatch.setattr(
        subject.machine_config,
        "active_connection",
        lambda **_kwargs: {"transport": "local-postgres"},
    )
    calls: list[list[str]] = []
    module = SimpleNamespace(main=lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(subject.importlib, "import_module", lambda _name: module)

    assert subject.migration_rehearse(["YOK-7"]) == 0
    assert calls == [["rehearse", "YOK-7"]]


def test_direct_authority_can_override_https_connection(monkeypatch) -> None:
    monkeypatch.setattr(subject, "local_authority_is_pinned", lambda: True)
    monkeypatch.setattr(
        subject.machine_config,
        "active_connection",
        lambda **_kwargs: {"transport": "https"},
    )
    module = SimpleNamespace(main=lambda argv: 0)
    monkeypatch.setattr(subject.importlib, "import_module", lambda _name: module)

    assert subject.migration_rehearse(["YOK-8"]) == 0


def test_aggregate_tool_registry_routes_public_command() -> None:
    from yoke_cli.commands.tool_shaped import resolve_tool_shaped

    resolved = resolve_tool_shaped(["migration", "rehearse", "YOK-9"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is subject.migration_rehearse
    assert remaining == ["YOK-9"]

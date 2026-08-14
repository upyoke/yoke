"""Tests for the human-only coordination-lease recovery command."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_cli.commands import coordination_lease as subject


def test_https_connection_is_refused_before_runtime_import(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(subject, "remote_without_admin_authority", lambda: True)
    monkeypatch.setattr(
        subject.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(AssertionError("must not import")),
    )

    assert subject.coordination_lease_release([]) == 1
    assert "not relayed over HTTPS" in capsys.readouterr().err


def test_local_authority_delegates_to_audited_operator_surface(monkeypatch) -> None:
    monkeypatch.setattr(subject, "remote_without_admin_authority", lambda: False)
    calls: list[list[str]] = []
    module = SimpleNamespace(
        cmd_coordination_lease_release=lambda args: calls.append(args) or 0,
    )
    monkeypatch.setattr(subject.importlib, "import_module", lambda _name: module)
    args = [
        "--project",
        "yoke",
        "--key",
        "LIVE_DB_MIGRATION:primary",
        "--reason",
        "stale holder confirmed",
    ]

    assert subject.coordination_lease_release(args) == 0
    assert calls == [args]


def test_aggregate_tool_registry_routes_public_command() -> None:
    from yoke_cli.commands.tool_shaped import resolve_tool_shaped

    resolved = resolve_tool_shaped(
        ["coordination-lease", "release", "--project", "yoke"]
    )
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is subject.coordination_lease_release
    assert remaining == ["--project", "yoke"]

"""Tests for the source-dev/admin migration rehearsal wrapper."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_cli.commands import migration_rehearse as subject
from yoke_contracts.migration_rehearsal_teaching import PROVISION_RECIPE


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
    refusal = capsys.readouterr().err
    assert "not relayed over HTTPS" in refusal
    # The refusal has to name how to FIND a usable connection, not only that
    # this one is unusable: `connection set` writes one, it does not list them.
    assert subject.CONNECTION_READER in refusal
    assert subject.PREFLIGHT_HELP_COMMAND in refusal


def test_help_names_every_binding_rehearsal_needs(capsys) -> None:
    with pytest.raises(SystemExit):
        subject.migration_rehearse(["--help"])

    rendered = capsys.readouterr().out
    assert subject.CONNECTION_READER in rendered
    assert "YOKE_PG_DSN_VALIDATION" in rendered
    assert PROVISION_RECIPE in rendered


def test_unexpected_failure_stays_redacted_but_points_at_the_preflight(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(subject, "local_authority_is_pinned", lambda: False)
    monkeypatch.setattr(
        subject.machine_config,
        "active_connection",
        lambda **_kwargs: {"transport": "local-postgres"},
    )
    monkeypatch.setattr(
        subject.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(
            RuntimeError("host=authority password=top-secret")
        ),
    )

    assert subject.migration_rehearse(["YOK-2"]) == 1
    reported = capsys.readouterr().err
    assert "top-secret" not in reported
    assert subject.PREFLIGHT_HELP_COMMAND in reported


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


def test_prod_db_admin_delegates_to_validation_runner(monkeypatch) -> None:
    """The durable authority records receipts but never receives migration DDL."""

    monkeypatch.setattr(
        subject,
        "local_authority_is_pinned",
        lambda: False,
    )
    monkeypatch.setattr(
        subject.machine_config,
        "active_connection",
        lambda **_kwargs: {"transport": "local-postgres", "prod": True},
    )
    calls: list[list[str]] = []
    module = SimpleNamespace(main=lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(subject.importlib, "import_module", lambda _name: module)

    assert subject.migration_rehearse(["YOK-1"]) == 0
    assert calls == [["rehearse", "YOK-1"]]

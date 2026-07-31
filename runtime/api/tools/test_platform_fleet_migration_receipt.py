"""Platform fleet-migration receipt reader CLI tests."""

from __future__ import annotations

import pytest

from runtime.api.tools import platform_fleet_migration_receipt as receipt


def test_help_does_not_resolve_database_authority(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unexpected_dsn() -> str:
        raise AssertionError("--help must not resolve a database DSN")

    monkeypatch.setattr(receipt, "_platform_dsn", unexpected_dsn)
    with pytest.raises(SystemExit) as raised:
        receipt.main(["--help"])

    assert raised.value.code == 0
    assert "run_id" in capsys.readouterr().out


def test_extra_positional_argument_is_rejected_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_dsn() -> str:
        raise AssertionError("invalid arguments must not resolve a database DSN")

    monkeypatch.setattr(receipt, "_platform_dsn", unexpected_dsn)
    with pytest.raises(SystemExit) as raised:
        receipt.main(["run-a", "run-b"])

    assert raised.value.code == 2

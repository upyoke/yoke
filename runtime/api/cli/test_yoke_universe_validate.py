import json
from types import SimpleNamespace

from yoke_cli.commands import tool_shaped
from yoke_cli.commands import universe_validate as adapter


def test_static_validation_is_first_class(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        adapter.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            inspect_archive=lambda archive: {
                "ok": True,
                "archive": archive,
                "bytes": 12,
                "table_entries": 4,
            }
        ),
    )

    assert adapter.universe_validate(["archive.dump", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_roundtrip_uses_explicit_validation_dsn(monkeypatch, capsys) -> None:
    seen = {}

    def validate(archive, dsn):
        seen.update(archive=archive, dsn=dsn)
        return {
            "ok": True,
            "archive": archive,
            "bytes": 12,
            "table_entries": 4,
            "roundtrip": True,
            "organization": "default",
            "schema_fingerprint": "fingerprint",
        }

    monkeypatch.setenv(adapter.VALIDATION_DSN_ENV, "dbname=disposable")
    monkeypatch.setenv(adapter.ROUNDTRIP_CONFIRM_ENV, "1")
    monkeypatch.setattr(
        adapter.importlib,
        "import_module",
        lambda _name: SimpleNamespace(validate_archive_roundtrip=validate),
    )

    assert adapter.universe_validate(["archive.dump", "--roundtrip"]) == 0
    assert seen == {"archive": "archive.dump", "dsn": "dbname=disposable"}
    assert "round-trip: valid" in capsys.readouterr().out


def test_roundtrip_requires_disposable_confirmation(monkeypatch, capsys) -> None:
    monkeypatch.setenv(adapter.VALIDATION_DSN_ENV, "dbname=disposable")
    monkeypatch.delenv(adapter.ROUNDTRIP_CONFIRM_ENV, raising=False)

    assert adapter.universe_validate(["archive.dump", "--roundtrip"]) == 1
    assert adapter.ROUNDTRIP_CONFIRM_ENV in capsys.readouterr().err


def test_tool_shaped_resolution_covers_universe_validate() -> None:
    resolved, tail = tool_shaped.resolve_tool_shaped(
        ["universe", "validate", "archive.dump"]
    )
    assert resolved is adapter.universe_validate
    assert tail == ["archive.dump"]

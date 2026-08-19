import json
from types import SimpleNamespace

from yoke_cli.commands import tool_shaped
from yoke_cli.commands import universe_validate as adapter
from yoke_core.domain import migration_validation_binding as validation_binding


def _engine_modules(monkeypatch, **by_module) -> None:
    """Stub the engine modules the adapter reaches for, keyed by module name.

    The adapter imports more than one, so a stub that ignores the requested
    name would answer every lookup with whichever module the test happened to
    care about.
    """

    def import_module(name: str) -> SimpleNamespace:
        return by_module[name.rsplit(".", 1)[-1]]

    monkeypatch.setattr(adapter.importlib, "import_module", import_module)


def test_static_validation_is_first_class(monkeypatch, capsys) -> None:
    _engine_modules(
        monkeypatch,
        universe_archive_validation=SimpleNamespace(
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
    _engine_modules(
        monkeypatch,
        universe_archive_validation=SimpleNamespace(
            validate_archive_roundtrip=validate
        ),
        migration_validation_binding=SimpleNamespace(
            read_binding=lambda env_var: "dbname=disposable"
        ),
    )

    assert adapter.universe_validate(["archive.dump", "--roundtrip"]) == 0
    assert seen == {"archive": "archive.dump", "dsn": "dbname=disposable"}
    assert "round-trip: valid" in capsys.readouterr().out


def test_roundtrip_reads_the_binding_rehearsal_provisioning_wrote(
    monkeypatch, capsys
) -> None:
    """One binding, two readers: a provisioned database needs no re-export."""
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

    monkeypatch.delenv(adapter.VALIDATION_DSN_ENV, raising=False)
    monkeypatch.setenv(adapter.ROUNDTRIP_CONFIRM_ENV, "1")
    validation_binding.write_binding(
        adapter.VALIDATION_DSN_ENV, "dbname=provisioned_scratch"
    )
    _engine_modules(
        monkeypatch,
        universe_archive_validation=SimpleNamespace(
            validate_archive_roundtrip=validate
        ),
        migration_validation_binding=validation_binding,
    )

    assert adapter.universe_validate(["archive.dump", "--roundtrip"]) == 0
    assert seen["dsn"] == "dbname=provisioned_scratch"
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

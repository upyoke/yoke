import json
from types import SimpleNamespace

from yoke_cli.commands import source_authority, tool_shaped
from yoke_cli import product_boundary_inventory


def test_begin_requires_attended_service_stop_receipt(capsys):
    assert source_authority.source_authority_quiesce([
        "begin", "--credential-file", "/secure/cutover.json",
    ]) == 2
    assert "service-stop-receipt" in capsys.readouterr().err


def test_begin_dispatches_client_local_admin_surface(monkeypatch, capsys):
    seen = {}

    def begin(**kwargs):
        seen.update(kwargs)
        return {
            "operation": "begin", "quiesced": True,
            "authority": {"receipt_digest": "a" * 64},
        }

    monkeypatch.setattr(
        source_authority.importlib, "import_module",
        lambda _name: SimpleNamespace(begin=begin),
    )
    rc = source_authority.source_authority_quiesce([
        "begin", "--service-stop-receipt", "stopped-123", "--json",
        "--credential-file", "/secure/cutover.json",
    ])
    assert rc == 0
    assert seen == {
        "credential_file": "/secure/cutover.json",
        "service_stop_receipt": "stopped-123",
    }
    assert json.loads(capsys.readouterr().out)["quiesced"] is True


def test_database_failures_return_safe_operator_errors(monkeypatch, capsys):
    def fail(**_kwargs):
        raise RuntimeError(
            "source authority database operation failed; inspect the "
            "PostgreSQL service and selected prod-db-admin connection"
        )

    monkeypatch.setattr(
        source_authority.importlib, "import_module",
        lambda _name: SimpleNamespace(status=fail, export_quiesced=fail),
    )

    assert source_authority.source_authority_quiesce([
        "status", "--credential-file", "/secure/cutover.json",
    ]) == 1
    quiesce_error = capsys.readouterr().err
    assert "source authority database operation failed" in quiesce_error
    assert "do-not-echo" not in quiesce_error
    assert "private-db" not in quiesce_error

    assert source_authority.source_authority_export([
        "--out", "archive.dump",
        "--credential-file", "/secure/cutover.json",
    ]) == 1
    export_error = capsys.readouterr().err
    assert "source authority database operation failed" in export_error
    assert "do-not-echo" not in export_error
    assert "private-db" not in export_error


def test_retire_requires_recorded_receipt(capsys):
    assert source_authority.source_authority_quiesce([
        "retire", "--credential-file", "/secure/cutover.json",
    ]) == 2
    assert "retirement-receipt" in capsys.readouterr().err


def test_installed_tool_registry_includes_validate_and_source_authority():
    validate, validate_tail = tool_shaped.resolve_tool_shaped(
        ["universe", "validate", "archive.dump"]
    )
    quiesce, quiesce_tail = tool_shaped.resolve_tool_shaped(
        ["source-authority", "quiesce", "status"]
    )
    export, export_tail = tool_shaped.resolve_tool_shaped(
        ["source-authority", "export", "--out", "archive.dump"]
    )
    assert validate.__module__.endswith("universe_validate")
    assert validate_tail == ["archive.dump"]
    assert quiesce is source_authority.source_authority_quiesce
    assert quiesce_tail == ["status"]
    assert export is source_authority.source_authority_export
    assert export_tail == ["--out", "archive.dump"]


def test_source_authority_is_explicit_source_dev_admin_boundary():
    rows = {
        row.command_helper: row
        for row in product_boundary_inventory.generate_inventory()
    }
    assert rows["yoke source-authority quiesce"].disposition == (
        product_boundary_inventory.SOURCE_DEV_ADMIN
    )
    assert rows["yoke source-authority export"].disposition == (
        product_boundary_inventory.SOURCE_DEV_ADMIN
    )

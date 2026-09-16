"""CLI tests for explicit ``yoke dev setup``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import source_checkout_activation


@pytest.fixture(autouse=True)
def _stub_source_link(monkeypatch):
    """`yoke dev setup` shells out to a source-link subprocess that imports
    yoke_core + the top-level ``runtime`` package resolved from the checkout.
    These CLI tests use a minimal fake checkout (no ``packages/``), so the real
    subprocess resolves those only via ambient PYTHONPATH — which pytest places
    on ``sys.path`` but does NOT export as the ``PYTHONPATH`` env the subprocess
    inherits, so it fails under CI. Stub it (source-link has its own coverage in
    ``test_onboard_source_dev_apply.py``); these tests assert the DSN /
    machine-config writes, not source-link.
    """
    monkeypatch.setattr(
        source_checkout_activation,
        "_run_source_link_subprocess",
        lambda root, **_kwargs: {
            "mode": "source-link",
            "warnings": [],
            "machine_config_newly_registered": False,
        },
    )


def test_dev_setup_routes_tool_shaped() -> None:
    # `yoke dev setup` is a client-local installer command (machine config,
    # source link) with no dispatcher function id, so it routes
    # via the tool-shaped table rather than SUBCOMMAND_REGISTRY. See
    # installer_local.TOOL_SHAPED_SUBCOMMANDS + operation_inventory
    # PERMANENT_ROWS; HC-fallback-registry-coherence must not expect a handler.
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS

    assert ("dev", "setup") not in SUBCOMMAND_REGISTRY
    assert ("dev", "setup") in TOOL_SHAPED_SUBCOMMANDS
    assert ("dev", "db-admin", "setup") in TOOL_SHAPED_SUBCOMMANDS


def test_dev_setup_apply_imports_dsn_into_machine_secret(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    checkout = _source_checkout(tmp_path)
    config = machine_home / "config.json"
    dsn = "postgresql://admin:secret@127.0.0.1:5432/yoke"

    rc = yoke_operations_cli.main(
        [
            "dev",
            "setup",
            str(checkout),
            "--dsn",
            dsn,
            "--config",
            str(config),
            "--yes",
            "--json",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["operation"] == "dev.setup"
    assert payload["applied"] is True
    assert payload["source_link"]["mode"] == "source-link"
    assert payload["admin_connection"]["connection"]["credential_source"] == {
        "kind": "dsn_file",
        "path": str(machine_home / "secrets" / "source-dev-admin.dsn"),
    }
    assert payload["admin_connection"]["connection"]["prod"] is False
    assert dsn not in captured.out
    assert dsn not in captured.err

    stored_dsn = machine_home / "secrets" / "source-dev-admin.dsn"
    assert stored_dsn.read_text(encoding="utf-8") == dsn + "\n"
    config_payload = json.loads(config.read_text(encoding="utf-8"))
    assert dsn not in config.read_text(encoding="utf-8")
    assert config_payload["connections"]["source-dev-admin"]["transport"] == (
        "local-postgres"
    )
    assert config_payload["connections"]["source-dev-admin"]["prod"] is False


def test_dev_setup_apply_accepts_positional_dsn(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    checkout = _source_checkout(tmp_path)
    config = machine_home / "config.json"
    dsn = "postgresql://admin:secret@127.0.0.1:5432/yoke"

    rc = yoke_operations_cli.main(
        [
            "dev",
            "setup",
            str(checkout),
            dsn,
            "--config",
            str(config),
            "--yes",
            "--json",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["admin_connection"]["connection"]["credential_source"] == {
        "kind": "dsn_file",
        "path": str(machine_home / "secrets" / "source-dev-admin.dsn"),
    }
    assert dsn not in captured.out
    assert dsn not in captured.err
    assert dsn not in config.read_text(encoding="utf-8")
    assert (machine_home / "secrets" / "source-dev-admin.dsn").read_text(
        encoding="utf-8"
    ) == dsn + "\n"


def test_dev_setup_apply_accepts_positional_dsn_from_source_cwd(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    checkout = _source_checkout(tmp_path)
    monkeypatch.chdir(checkout)
    config = machine_home / "config.json"
    dsn = "postgresql://admin:secret@127.0.0.1:5432/yoke"

    rc = yoke_operations_cli.main(
        [
            "dev",
            "setup",
            dsn,
            "--config",
            str(config),
            "--yes",
            "--json",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["checkout"]["path"] == str(checkout.resolve())
    assert dsn not in captured.out
    assert dsn not in captured.err
    assert dsn not in config.read_text(encoding="utf-8")
    assert (machine_home / "secrets" / "source-dev-admin.dsn").read_text(
        encoding="utf-8"
    ) == dsn + "\n"


def test_dev_setup_apply_accepts_positional_libpq_dsn_from_source_cwd(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    checkout = _source_checkout(tmp_path)
    monkeypatch.chdir(checkout)
    config = machine_home / "config.json"
    dsn = "host=/tmp user=yoke dbname=postgres"

    rc = yoke_operations_cli.main(
        [
            "dev",
            "setup",
            dsn,
            "--config",
            str(config),
            "--yes",
            "--json",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["checkout"]["path"] == str(checkout.resolve())
    assert dsn not in captured.out
    assert dsn not in captured.err
    assert dsn not in config.read_text(encoding="utf-8")
    assert (machine_home / "secrets" / "source-dev-admin.dsn").read_text(
        encoding="utf-8"
    ) == dsn + "\n"


def test_dev_setup_reused_local_postgres_marks_non_prod(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    checkout = _source_checkout(tmp_path)
    config = machine_home / "config.json"
    secret_path = machine_home / "secrets" / "source-dev-admin.dsn"
    secret_path.parent.mkdir(parents=True)
    secret_path.parent.chmod(0o700)
    secret_path.write_text(
        "postgresql://admin@localhost/yoke\n",
        encoding="utf-8",
    )
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "source-dev-admin",
                "connections": {
                    "source-dev-admin": {
                        "transport": "local-postgres",
                        "credential_source": {
                            "kind": "dsn_file",
                            "path": str(secret_path),
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    rc = yoke_operations_cli.main(
        [
            "dev",
            "setup",
            str(checkout),
            "--config",
            str(config),
            "--set-active-env",
            "--yes",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["admin_connection"]["connection"]["prod"] is False
    entry = json.loads(config.read_text(encoding="utf-8"))["connections"][
        "source-dev-admin"
    ]
    assert entry["prod"] is False


def _source_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "yoke-source"
    (checkout / "runtime" / "harness").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n',
        encoding="utf-8",
    )
    return checkout

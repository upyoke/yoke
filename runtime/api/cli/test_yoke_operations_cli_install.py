"""CLI round-trip tests for ``yoke project install/refresh/uninstall``."""

from __future__ import annotations

import json

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.project_install import transport as project_install_transport
from yoke_core.domain import project_install
from yoke_core.domain.project_install_test_helpers import (
    DEFAULT_CONTRACT_FILES,
    make_bundle,
)
from yoke_contracts.machine_config import schema as contract


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return tmp_path / "machine-home" / "config.json"


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture()
def fake_bundle(monkeypatch):
    monkeypatch.setattr(
        project_install, "_resolve_bundle",
        lambda pid, **kw: (make_bundle(), "test"),
    )


def _seed_connection(cfg, tmp_path) -> None:
    token = tmp_path / "api.token"
    token.write_text("test-token\n", encoding="utf-8")
    rc = yoke_operations_cli.main([
        "connection", "set", "local",
        "--transport", "https",
        "--api-url", "http://127.0.0.1:1",
        "--token-file", str(token),
        "--config", str(cfg),
    ])
    assert rc == 0


def _seed_local_postgres_connection(cfg, tmp_path) -> None:
    dsn = tmp_path / "local.dsn"
    dsn.write_text("postgresql://localhost/yoke\n", encoding="utf-8")
    rc = yoke_operations_cli.main([
        "connection", "set", "source-dev-admin",
        "--transport", "local-postgres",
        "--dsn-file", str(dsn),
        "--config", str(cfg),
    ])
    assert rc == 0


def test_install_then_refresh_then_uninstall_round_trip(
    cfg, repo, fake_bundle, tmp_path, capsys
) -> None:
    _seed_connection(cfg, tmp_path)
    capsys.readouterr()

    rc = yoke_operations_cli.main([
        "project", "install", str(repo),
        "--project-id", "7", "--config", str(cfg), "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["operation"] == "install"
    assert report["machine_config_newly_registered"] is True
    assert report["snapshot_sync"]["status"] == "skipped"
    assert report["snapshot_sync"]["repair_command"].endswith("--project 7")
    assert (repo / ".claude/skills/yoke/onboard-project/SKILL.md").is_file()
    assert (repo / ".yoke/install-manifest.json").is_file()
    assert report["worktrees_ignore"]["status"] == "written"
    assert report["worktrees_ignore"]["patch"] == ["+.worktrees/"]
    assert (repo / ".gitignore").read_text(encoding="utf-8") == ".worktrees/\n"
    assert sorted(report["contract_files_written"]) == sorted(
        e["path"] for e in DEFAULT_CONTRACT_FILES
    )
    assert (repo / ".yoke/board.json").is_file()

    # Project edits to seeded contract files survive refresh.
    (repo / ".yoke/board.json").write_text(
        '{"art_override": "frontier"}\n', encoding="utf-8"
    )

    # Refresh resolves the project id from the registered mapping.
    rc = yoke_operations_cli.main([
        "project", "refresh", str(repo), "--config", str(cfg), "--json",
    ])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["operation"] == "refresh"
    assert report["files_written"] == []
    assert report["contract_files_written"] == []
    assert report["worktrees_ignore"]["status"] == "present"
    assert report["worktrees_ignore"]["patch"] == []
    assert ".yoke/board.json" in report["contract_files_existing"]
    assert (repo / ".yoke/board.json").read_text("utf-8") == (
        '{"art_override": "frontier"}\n'
    )

    rc = yoke_operations_cli.main([
        "project", "uninstall", str(repo), "--config", str(cfg), "--json",
    ])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["operation"] == "uninstall"
    assert not (repo / ".yoke/install-manifest.json").exists()
    assert not (repo / ".claude").exists()
    assert report["contract_files_preserved_modified"] == [
        ".yoke/board.json"
    ]
    assert (repo / ".yoke/board.json").is_file(), (
        "edited contract file survives uninstall"
    )
    assert ".yoke/lint-config" in report["contract_files_removed"]
    assert not (repo / ".yoke/lint-config").exists()


def test_install_without_project_id_exits_nonzero(cfg, repo, capsys) -> None:
    rc = yoke_operations_cli.main([
        "project", "install", str(repo), "--config", str(cfg),
    ])

    assert rc == 1
    assert "--project-id" in capsys.readouterr().err


def test_install_accepts_non_prod_local_postgres_bundle(
    cfg, repo, tmp_path, capsys, monkeypatch,
) -> None:
    _seed_local_postgres_connection(cfg, tmp_path)
    capsys.readouterr()

    def _fetch_local(project_id, connection, config_path):
        assert project_id == 7
        assert connection["env"] == "source-dev-admin"
        assert connection["transport"] == contract.DEFAULT_TRANSPORT
        assert str(config_path) == str(cfg)
        return make_bundle()

    monkeypatch.setattr(
        project_install_transport,
        "_fetch_bundle_local_postgres",
        _fetch_local,
    )

    rc = yoke_operations_cli.main([
        "project", "install", str(repo),
        "--project-id", "7", "--config", str(cfg), "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["operation"] == "install"
    assert report["source"] == "local-postgres:source-dev-admin"
    assert (repo / ".yoke/install-manifest.json").exists()
    assert (repo / ".claude/skills/yoke/onboard-project/SKILL.md").is_file()


def test_install_refuses_prod_marked_local_postgres_before_repo_writes(
    cfg, repo, tmp_path, capsys,
) -> None:
    dsn = tmp_path / "prod.dsn"
    dsn.write_text("postgresql://localhost/yoke_prod\n", encoding="utf-8")
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        json.dumps({
            "schema_version": 1,
            "active_env": "prod-db-admin",
            "connections": {
                "prod-db-admin": {
                    "transport": contract.DEFAULT_TRANSPORT,
                    "prod": True,
                    "credential_source": {
                        "kind": contract.CREDENTIAL_KIND_DSN_FILE,
                        "path": str(dsn),
                    },
                },
            },
            "settings": {},
        }) + "\n",
        encoding="utf-8",
    )

    rc = yoke_operations_cli.main([
        "project", "install", str(repo),
        "--project-id", "7", "--config", str(cfg),
    ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "prod-marked local-postgres connection" in err
    assert not (repo / ".yoke/install-manifest.json").exists()
    assert not (repo / ".claude").exists()


def test_uninstall_without_manifest_exits_nonzero(cfg, repo, capsys) -> None:
    rc = yoke_operations_cli.main([
        "project", "uninstall", str(repo), "--config", str(cfg),
    ])

    assert rc == 1
    assert "install-manifest" in capsys.readouterr().err


@pytest.fixture()
def source_checkout(tmp_path):
    root = tmp_path / "yoke-src"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n', encoding="utf-8"
    )
    (root / "runtime" / "harness").mkdir(parents=True)
    return root


def test_install_source_checkout_hands_off_to_dev_setup(
    cfg, source_checkout, capsys
) -> None:
    rc = yoke_operations_cli.main([
        "project", "install", str(source_checkout), "--config", str(cfg),
    ])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "yoke dev setup" in captured.err
    assert "source-link" in captured.err
    assert not (source_checkout / ".claude" / "agents").exists()
    assert not (source_checkout / ".yoke/install-manifest.json").exists()


def test_source_checkout_refusal_is_repeatable(
    cfg, source_checkout, capsys
) -> None:
    rc = yoke_operations_cli.main([
        "project", "install", str(source_checkout),
        "--config", str(cfg),
    ])

    assert rc == 1
    assert "yoke dev setup" in capsys.readouterr().err


def test_project_install_help_does_not_advertise_source_dev_modes(capsys) -> None:
    rc = yoke_operations_cli.main([
        "project", "install", "--help",
    ])

    assert rc == 0
    out = capsys.readouterr().out
    assert "--source-link" not in out
    assert "source-link" not in out
    assert "source-dev" not in out

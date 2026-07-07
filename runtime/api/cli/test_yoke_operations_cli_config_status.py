from __future__ import annotations

import json
import os
from pathlib import Path

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import install_binding, status_render
from yoke_cli.config import status as machine_config_status
from yoke_contracts.machine_config import schema as contract


def _stub_server_health(monkeypatch, payload):
    """Pin the one-health-call server probe; tests never touch the network."""
    monkeypatch.setattr(
        machine_config_status,
        "_fetch_server_health",
        lambda api_url, timeout_s=None: payload,
    )


def _status_config(tmp_path: Path, repo: Path) -> Path:
    temp_root = tmp_path / "tmp"
    cache_dir = tmp_path / "cache"
    temp_root.mkdir()
    cache_dir.mkdir()
    (repo / ".yoke").mkdir(parents=True)
    (repo / ".yoke" / "board.json").write_text(
        json.dumps({"timeline_widget": "always", "dashboard_weather": False}),
        encoding="utf-8",
    )
    token_file = tmp_path / "actor-token"
    token_file.write_text("secret-token\n", encoding="utf-8")
    token_file.chmod(0o600)
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({
            "schema_version": 1,
            "active_env": "prod",
            "connections": {
                "prod": {
                    "transport": "https",
                    "prod": True,
                    "api_url": "https://api.upyoke.com/v1",
                    "credential_source": {
                        "kind": "token_file",
                        "path": str(token_file),
                    },
                },
            },
            "temp_root": str(temp_root),
            "cache_dir": str(cache_dir),
            "projects": {
                str(repo.resolve()): {
                    "project_id": 1,
                    "board": {
                        "scope": "all",
                        "render_path": ".yoke/BOARD-ALL.md",
                    },
                },
            },
        }),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_config_example_prints_canonical_json(capsys) -> None:
    rc = yoke_operations_cli.main(["config", "example"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == contract.canonical_example_payload()


def test_status_json_validates_machine_and_project_config(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = _status_config(tmp_path, repo)
    _stub_server_health(monkeypatch, {"engine_version": "2.0.0"})

    rc = yoke_operations_cli.main([
        "status",
        "--config", str(config),
        "--repo-root", str(repo),
        "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["config"]["exists"] is True
    assert report["config"]["owner_only"] is True
    assert report["connection"]["transport"] == "https"
    assert report["connection"]["prod"] is True
    assert report["connection"]["envs"] == ["prod"]
    assert report["project"]["project_id"] == 1
    assert report["project"]["board_scope"] == "all"
    assert report["project"]["board_config_path"].endswith(".yoke/board.json")
    assert report["project"]["board_render_path"].endswith("BOARD-ALL.md")
    assert report["project"]["board_ts_path"].endswith("BOARD-ALL.md.ts")
    assert report["project"]["board_art_path"].endswith(".yoke/board-art")
    assert report["paths"]["temp_root"]["writable"] is True
    assert report["paths"]["cache_dir"]["writable"] is True


def _synthetic_checkout(root: Path) -> Path:
    """Materialize the structural markers of a Yoke source checkout."""
    (root / "runtime" / "harness").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n', encoding="utf-8",
    )
    module_file = root / "packages" / "yoke-cli" / "src" / "yoke_cli" / "__init__.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")
    return module_file


def test_install_binding_detects_source_checkout(tmp_path: Path) -> None:
    module_file = _synthetic_checkout(tmp_path / "checkout")

    binding = install_binding.detect(module_file)

    assert binding["kind"] == install_binding.KIND_SOURCE_CHECKOUT
    assert binding["checkout_root"] == str(tmp_path / "checkout")
    assert binding["module_origin"] == str(module_file)


def test_install_binding_detects_packaged_wheel(tmp_path: Path) -> None:
    module_file = (
        tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
        / "yoke_cli" / "__init__.py"
    )
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")

    binding = install_binding.detect(module_file)

    assert binding["kind"] == install_binding.KIND_PACKAGED_WHEEL
    assert binding["checkout_root"] is None
    assert binding["module_origin"] == str(module_file)


def test_install_binding_wheel_venv_inside_checkout_stays_packaged(
    tmp_path: Path,
) -> None:
    """Source presence never activates: a wheel venv nested inside a checkout
    still reports the packaged binding because the import resolves from
    site-packages, not the checkout's packages/ source tree."""
    checkout = tmp_path / "checkout"
    _synthetic_checkout(checkout)
    venv_module = (
        checkout / ".venv" / "lib" / "python3.12" / "site-packages"
        / "yoke_cli" / "__init__.py"
    )
    venv_module.parent.mkdir(parents=True)
    venv_module.write_text("", encoding="utf-8")

    binding = install_binding.detect(venv_module)

    assert binding["kind"] == install_binding.KIND_PACKAGED_WHEEL
    assert binding["checkout_root"] is None


def test_render_human_states_install_binding_for_both_shapes() -> None:
    packaged = status_render.render_human(
        {"install": {"kind": install_binding.KIND_PACKAGED_WHEEL,
                     "checkout_root": None, "version": "1.2.3"}},
    )
    source = status_render.render_human(
        {"install": {"kind": install_binding.KIND_SOURCE_CHECKOUT,
                     "checkout_root": "/somewhere/yoke", "version": "1.2.3"}},
    )

    assert "  install: packaged wheel 1.2.3" in packaged
    assert "  install: source checkout /somewhere/yoke" in source


def test_status_json_reports_install_binding(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = _status_config(tmp_path, repo)
    _stub_server_health(monkeypatch, {"engine_version": "2.0.0"})

    rc = yoke_operations_cli.main([
        "status",
        "--config", str(config),
        "--repo-root", str(repo),
        "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    # The test process imports yoke_cli from a source tree, never a wheel.
    assert report["install"]["kind"] == install_binding.KIND_SOURCE_CHECKOUT
    assert report["install"]["checkout_root"]
    assert report["install"]["module_origin"].endswith("yoke_cli/__init__.py")


def test_global_env_override_is_restored(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = _status_config(tmp_path, repo)
    _stub_server_health(monkeypatch, {"engine_version": "2.0.0"})
    monkeypatch.delenv(contract.ENV_OVERRIDE, raising=False)

    rc = yoke_operations_cli.main([
        "--env", "prod",
        "status",
        "--config", str(config),
        "--repo-root", str(repo),
        "--json",
    ])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["connection"]["env"] == "prod"
    assert contract.ENV_OVERRIDE not in os.environ


def test_status_https_reports_server_engine_version(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    """One stubbed health call surfaces the server's engine version."""
    repo = tmp_path / "repo"
    repo.mkdir()
    config = _status_config(tmp_path, repo)
    _stub_server_health(
        monkeypatch, {"engine_version": "2.0.0", "build": "abc123def456"},
    )

    rc = yoke_operations_cli.main([
        "status", "--config", str(config), "--repo-root", str(repo), "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["server"] == {
        "relevant": True,
        "reachable": True,
        "engine_version": "2.0.0",
        "build": "abc123def456",
    }


def test_status_https_degrades_when_server_unreachable(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    """An unreachable server is a warning, never an error: rc stays 0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    config = _status_config(tmp_path, repo)
    _stub_server_health(monkeypatch, None)

    rc = yoke_operations_cli.main([
        "status", "--config", str(config), "--repo-root", str(repo), "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["server"]["reachable"] is False
    assert report["server"]["engine_version"] == ""
    codes = {issue["code"] for issue in report["issues"]}
    assert "server_unreachable" in codes


def test_render_human_shows_server_engine_line() -> None:
    reachable = status_render.render_human(
        {"server": {"relevant": True, "reachable": True,
                    "engine_version": "2.0.0"}},
    )
    unreachable = status_render.render_human(
        {"server": {"relevant": True, "reachable": False,
                    "engine_version": ""}},
    )
    local_only = status_render.render_human(
        {"server": {"relevant": False, "reachable": None,
                    "engine_version": ""}},
    )

    assert "  server: engine=2.0.0" in reachable
    assert "  server: unreachable (engine version unknown)" in unreachable
    assert "server:" not in local_only

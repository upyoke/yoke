from __future__ import annotations

import json
import os
from importlib.machinery import ModuleSpec
from pathlib import Path

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import (
    install_binding,
    status as status_module,
    status_render,
)
from yoke_contracts.machine_config import schema as contract

from runtime.api.cli.status_test_helpers import status_config, stub_server


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
    config = status_config(tmp_path, repo)
    stub_server(monkeypatch, {"engine_version": "2.0.0"})

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
    assert binding["version"] == ""


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
    assert binding["version"] == ""


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
    config = status_config(tmp_path, repo)
    stub_server(monkeypatch, {"engine_version": "2.0.0"})

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
    assert report["install"]["version"] == ""
    assert set(report["runtime"]["package_versions"].values()) == {""}


def test_packaged_core_version_uses_metadata_without_module_probe(
    monkeypatch,
) -> None:
    probed: list[str] = []

    def fake_find_spec(name: str):
        probed.append(name)
        if name == "yoke_core":
            raise AssertionError("packaged HTTPS status must not probe yoke_core")
        return ModuleSpec(name, loader=None, origin=f"/product/{name}.py")

    monkeypatch.setattr(status_module.importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setattr(
        status_module,
        "metadata_version",
        lambda name: "4.5.6" if name == "yoke-core" else "",
    )

    version = status_module._package_version(  # noqa: SLF001
        "yoke-core", source_bound=False,
    )

    assert version == "4.5.6"
    assert "yoke_core" not in probed


def test_source_bound_package_versions_ignore_ambient_metadata(
    monkeypatch,
) -> None:
    def fail_probe(name: str):
        raise AssertionError(f"source status must not probe {name}")

    def fail_metadata(name: str):
        raise AssertionError(f"source status must ignore metadata for {name}")

    monkeypatch.setattr(
        status_module.importlib.util,
        "find_spec",
        fail_probe,
    )
    monkeypatch.setattr(
        status_module,
        "metadata_version",
        fail_metadata,
    )

    versions = {
        name: status_module._package_version(name, source_bound=True)  # noqa: SLF001
        for name in status_module.PRODUCT_RUNTIME_PACKAGES
    }

    assert set(versions.values()) == {""}


def test_global_env_override_is_restored(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = status_config(tmp_path, repo)
    stub_server(monkeypatch, {"engine_version": "2.0.0"})
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

"""Install-binding parity between the two ``status`` report surfaces.

``yoke status`` builds its report CLI-locally (``yoke_cli.config.status``)
while the ``status.run`` function id dispatches to the yoke-core twin
(``yoke_core.domain.machine_config_status``). Both must emit one JSON
shape for the ``install`` field, backed by the shared detector in
``yoke_contracts.install_binding``.
"""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import install_binding as cli_install_binding
from yoke_contracts import install_binding as contract
from yoke_core.domain import machine_config_status


def _synthetic_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "yoke"
    module_dir = root / "packages" / "yoke-core" / "src" / "yoke_core"
    module_dir.mkdir(parents=True)
    (module_dir / "__init__.py").write_text("")
    (root / "pyproject.toml").write_text('[project]\nname = "yoke"\n')
    (root / "runtime" / "harness").mkdir(parents=True)
    return root


def test_contract_detects_checkout_module_origin(tmp_path: Path) -> None:
    root = _synthetic_checkout(tmp_path)
    module_file = root / "packages" / "yoke-core" / "src" / "yoke_core" / "__init__.py"
    assert contract.source_checkout_root(module_file) == root


def test_contract_rejects_site_packages_origin(tmp_path: Path) -> None:
    module_file = (
        tmp_path / "venv" / "lib" / "python3.13" / "site-packages"
        / "yoke_core" / "__init__.py"
    )
    module_file.parent.mkdir(parents=True)
    module_file.write_text("")
    assert contract.source_checkout_root(module_file) is None


class _Distribution:
    def __init__(self, root: Path, version: str, files: tuple[Path, ...] = ()) -> None:
        self._root = root
        self.version = version
        self.files = files

    def locate_file(self, path: str | Path) -> Path:
        return self._root / path


def test_distribution_version_requires_matching_packaged_origin(
    tmp_path: Path, monkeypatch,
) -> None:
    site_packages = tmp_path / "venv" / "site-packages"
    module_file = site_packages / "yoke_cli" / "__init__.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("")
    monkeypatch.setattr(
        contract,
        "_distribution",
        lambda _name: _Distribution(
            site_packages,
            "7.8.9",
            (Path("yoke_cli/__init__.py"),),
        ),
    )

    assert contract.distribution_version_for_module("yoke-cli", module_file) == "7.8.9"
    assert contract.distribution_version_for_module(
        "yoke-cli", tmp_path / "other" / "yoke_cli" / "__init__.py"
    ) == ""


def test_distribution_version_ignores_stale_metadata_for_source(
    tmp_path: Path, monkeypatch,
) -> None:
    root = _synthetic_checkout(tmp_path)
    module_file = root / "packages" / "yoke-core" / "src" / "yoke_core" / "__init__.py"
    monkeypatch.setattr(
        contract,
        "_distribution",
        lambda _name: _Distribution(tmp_path / "site-packages", "99.0.0"),
    )

    assert contract.distribution_version_for_module("yoke-core", module_file) == ""
    assert contract.distribution_version_for_module(
        "yoke-core", module_file, source_value="source"
    ) == "source"


def test_twin_report_carries_install_binding(tmp_path: Path) -> None:
    report = machine_config_status.build_status(
        config_path=tmp_path / "config.json",
        repo_root=tmp_path,
        check_reachability=False,
    )
    install = report["install"]
    assert install["kind"] in (
        contract.KIND_PACKAGED_WHEEL, contract.KIND_SOURCE_CHECKOUT,
    )
    assert install["module_origin"].endswith("yoke_core/__init__.py")
    if install["kind"] == contract.KIND_SOURCE_CHECKOUT:
        assert install["checkout_root"]
        assert install["version"] == ""
    else:
        assert install["checkout_root"] is None


def test_twin_install_shape_matches_cli_detector(tmp_path: Path) -> None:
    report = machine_config_status.build_status(
        config_path=tmp_path / "config.json",
        repo_root=tmp_path,
        check_reachability=False,
    )
    cli_binding = cli_install_binding.detect()
    assert set(report["install"]) == set(cli_binding)


def test_twin_render_human_states_install_binding(tmp_path: Path) -> None:
    report = machine_config_status.build_status(
        config_path=tmp_path / "config.json",
        repo_root=tmp_path,
        check_reachability=False,
    )
    rendered = machine_config_status.render_human(report)
    assert "  install: " in rendered
    assert contract.label(report["install"]) in rendered

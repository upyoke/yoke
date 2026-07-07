"""Release artifact builder contract for Yoke product distribution."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from yoke_core.tools import build_release


def test_build_release_renders_pep503_simple_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    (asset_dir / "install.py").write_text("print('install')\n", encoding="utf-8")
    (asset_dir / "install").write_text("#!/bin/sh\n", encoding="utf-8")

    def fake_wheelhouse(*, wheelhouse: Path, **_: object) -> Path:
        wheelhouse.mkdir(parents=True)
        # Product wheels plus a third-party closure; only product wheels publish.
        for name, version in (
            ("yoke-contracts", "0.2.0"),
            ("yoke-cli", "0.2.0"),
            ("yoke-harness", "0.2.0"),
            ("yoke-core", "0.2.0"),
            ("pydantic", "2.13.4"),
            ("pyfiglet", "1.0.4"),
        ):
            _write_wheel(wheelhouse, name=name, version=version)
        return wheelhouse

    monkeypatch.setattr(build_release, "build_product_wheelhouse", fake_wheelhouse)

    result = build_release.build_release(
        repo_root=tmp_path,
        output_root=tmp_path / "release",
        base_url="https://api.upyoke.com",
        channel="stable",
        generated_at="2026-06-18T00:00:00+00:00",
        installer_asset_dir=asset_dir,
    )

    assert result.version == "0.2.0"
    assert result.index_url == "https://api.upyoke.com/simple/"
    release_dir = result.paths.release_dir
    assert release_dir == tmp_path / "release" / "dist" / "releases" / "0.2.0"

    # Installer assets and immutable versioned product wheels.
    assert (tmp_path / "release" / "install").read_text(encoding="utf-8")
    assert (tmp_path / "release" / "dist" / "install.py").is_file()
    wheels_dir = release_dir / "wheels"
    # Third-party wheels are NOT hosted; only the product wheels.
    assert sorted(p.name for p in wheels_dir.glob("*.whl")) == [
        "yoke_cli-0.2.0-py3-none-any.whl",
        "yoke_contracts-0.2.0-py3-none-any.whl",
        "yoke_core-0.2.0-py3-none-any.whl",
        "yoke_harness-0.2.0-py3-none-any.whl",
    ]
    # No wheelhouse zip, no per-target wheelhouse machinery.
    assert not (release_dir / "targets").exists()
    assert not list((tmp_path / "release").rglob("*.zip"))

    # PEP 503 root index lists the normalized product project names only.
    simple_dir = result.paths.simple_dir
    assert simple_dir == tmp_path / "release" / "simple"
    root_html = (simple_dir / "index.html").read_text(encoding="utf-8")
    for project in ("yoke-cli", "yoke-contracts", "yoke-harness", "yoke-core"):
        assert f'href="{project}/"' in root_html
    assert "pydantic" not in root_html

    # Per-project index links the wheel at its immutable versioned URL + sha256.
    cli_html = (simple_dir / "yoke-cli" / "index.html").read_text(encoding="utf-8")
    record = next(
        entry for entry in result.release_records if entry["project"] == "yoke-cli"
    )
    expected = (
        "https://api.upyoke.com/dist/releases/0.2.0/wheels/"
        f"yoke_cli-0.2.0-py3-none-any.whl#sha256={record['sha256']}"
    )
    assert expected in cli_html
    assert "yoke_cli-0.2.0-py3-none-any.whl</a>" in cli_html

    # release-records.json carries product sha256/size for publish-verify.
    records = json.loads(result.paths.release_records_path.read_text(encoding="utf-8"))
    assert {entry["project"] for entry in records} == {
        "yoke-cli",
        "yoke-contracts",
        "yoke-harness",
        "yoke-core",
    }
    assert not {"pydantic", "pyfiglet"}.intersection(
        entry["name"] for entry in records
    )

    # Channel pointer pins one version and names the served index URL.
    channel = json.loads(result.paths.channel_path.read_text(encoding="utf-8"))
    assert channel["schema_version"] == 2
    assert channel["channel"] == "stable"
    assert channel["version"] == "0.2.0"
    assert channel["index_url"] == "https://api.upyoke.com/simple/"
    assert channel["release_base_url"] == (
        "https://api.upyoke.com/dist/releases/0.2.0"
    )
    assert channel["generated_at"] == "2026-06-18T00:00:00+00:00"
    assert "wheelhouse" not in channel
    assert "manifest" not in channel
    assert "targets" not in channel
    assert channel["installer"]["python_url"] == (
        "https://api.upyoke.com/dist/install.py"
    )
    assert channel["installer"]["shell_url"] == "https://api.upyoke.com/install"


def test_build_release_quotes_local_version_public_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    (asset_dir / "install.py").write_text("print('install')\n", encoding="utf-8")
    (asset_dir / "install").write_text("#!/bin/sh\n", encoding="utf-8")

    def fake_wheelhouse(*, wheelhouse: Path, **_: object) -> Path:
        wheelhouse.mkdir(parents=True)
        for name in build_release.PRODUCT_PACKAGE_NAMES:
            _write_wheel(wheelhouse, name=name, version="0.2.0+gabc123")
        return wheelhouse

    monkeypatch.setattr(build_release, "build_product_wheelhouse", fake_wheelhouse)

    result = build_release.build_release(
        repo_root=tmp_path,
        output_root=tmp_path / "release",
        base_url="https://api.upyoke.com",
        channel="stable",
        generated_at="2026-06-18T00:00:00+00:00",
        installer_asset_dir=asset_dir,
    )

    channel = json.loads(result.paths.channel_path.read_text(encoding="utf-8"))
    assert channel["release_base_url"] == (
        "https://api.upyoke.com/dist/releases/0.2.0%2Bgabc123"
    )
    # The simple index links the local-version wheel with a quoted '+' in the URL.
    cli_html = (
        result.paths.simple_dir / "yoke-cli" / "index.html"
    ).read_text(encoding="utf-8")
    assert (
        "https://api.upyoke.com/dist/releases/0.2.0%2Bgabc123/wheels/"
        "yoke_cli-0.2.0%2Bgabc123-py3-none-any.whl#sha256="
    ) in cli_html
    # The link text is the unquoted filename.
    assert "yoke_cli-0.2.0+gabc123-py3-none-any.whl</a>" in cli_html


def test_build_release_refuses_missing_installer_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_wheelhouse(*, wheelhouse: Path, **_: object) -> Path:
        wheelhouse.mkdir(parents=True)
        for name in build_release.PRODUCT_PACKAGE_NAMES:
            _write_wheel(wheelhouse, name=name, version="0.2.0")
        return wheelhouse

    monkeypatch.setattr(build_release, "build_product_wheelhouse", fake_wheelhouse)

    with pytest.raises(build_release.ReleaseBuildError, match="missing installer"):
        build_release.build_release(
            repo_root=tmp_path,
            output_root=tmp_path / "release",
            base_url="https://api.upyoke.com",
            installer_asset_dir=tmp_path / "missing-assets",
        )


def test_build_product_wheelhouse_includes_bootstrap_pip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> None:
        commands.append(list(command))
        if "--package" in command:
            package = command[command.index("--package") + 1]
            _write_wheel(wheelhouse, name=package, version="0.2.0")
        elif "wheel" in command:
            _write_wheel(wheelhouse, name="pip", version="25.3")

    monkeypatch.setattr(build_release, "_uv_executable", lambda _: "uv")
    monkeypatch.setattr(build_release, "_run", fake_run)
    monkeypatch.setattr(
        build_release,
        "_pip_python",
        lambda _: _FixedPython(tmp_path / "python"),
    )

    build_release.build_product_wheelhouse(repo_root=tmp_path, wheelhouse=wheelhouse)

    assert build_release.BOOTSTRAP_REQUIREMENTS[0] in commands[-1]
    assert (wheelhouse / "pip-25.3-py3-none-any.whl").is_file()


def _write_wheel(wheelhouse: Path, *, name: str, version: str) -> None:
    dist = name.replace("-", "_")
    filename = f"{dist}-{version}-py3-none-any.whl"
    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
    )
    with zipfile.ZipFile(wheelhouse / filename, "w") as archive:
        archive.writestr(f"{dist}-{version}.dist-info/METADATA", metadata)


class _FixedPython:
    def __init__(self, path: Path) -> None:
        self._path = path

    def __enter__(self) -> Path:
        return self._path

    def __exit__(self, *exc: object) -> None:
        pass

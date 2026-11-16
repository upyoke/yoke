"""Windows Node distribution layout, execution and archive safety."""

import hashlib
import subprocess
import zipfile

import pytest

from yoke_cli import browser_node_toolchain as node
from yoke_cli.browser_node_archive import unpack_release


pytestmark = pytest.mark.windows


@pytest.mark.parametrize("machine,slug", [("AMD64", "win-x64"), ("ARM64", "win-arm64")])
def test_windows_clean_host_installs_and_reuses_zip(
    tmp_path, monkeypatch, machine, slug
):
    monkeypatch.setattr(node.platform, "system", lambda: "Windows")
    monkeypatch.setattr(node.platform, "machine", lambda: machine)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(node.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        node.terminal_detached_process,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(
            argv, 0, node.MANAGED_NODE_VERSION, ""
        ),
    )
    version = node.MANAGED_NODE_VERSION
    releases = tmp_path / "dist" / version
    releases.mkdir(parents=True)
    archive = releases / f"node-{version}-{slug}.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for name in [
            "node.exe",
            "npm.cmd",
            "npx.cmd",
            "node_modules/npm/bin/npm-cli.js",
            "node_modules/npm/bin/npx-cli.js",
        ]:
            handle.writestr(f"node-{version}-{slug}/{name}", "stand-in")
    monkeypatch.setitem(
        node._ARCHIVE_SHA256, slug, hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    chain = node.ensure_node_toolchain(base_url=releases.parent.as_uri())
    assert chain.bin_dir == node.managed_version_dir()
    assert chain.node.name == "node.exe"
    assert chain.npm.name == "npm.cmd"
    assert chain.npx.name == "npx.cmd"
    assert chain.package_command("npm", "install") == [
        str(chain.node),
        str(chain.bin_dir / "node_modules/npm/bin/npm-cli.js"),
        "install",
    ]
    assert chain.package_command("npx", "playwright", "install", "chromium") == [
        str(chain.node),
        str(chain.bin_dir / "node_modules/npm/bin/npx-cli.js"),
        "playwright",
        "install",
        "chromium",
    ]
    monkeypatch.setattr(
        node, "fetch_file", lambda *a, **kw: pytest.fail("repeat download")
    )
    assert node.ensure_node_toolchain() == chain


@pytest.mark.parametrize(
    "member", ["../escape", "/absolute", "C:/escape", "..\\escape"]
)
def test_zip_paths_cannot_escape_staging(tmp_path, member):
    archive = tmp_path / "node.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(member, "bad")
    with pytest.raises(node.NodeToolchainError) as error:
        unpack_release(
            archive,
            tmp_path,
            tmp_path / "installed",
            error_type=node.NodeToolchainError,
        )
    assert error.value.code == "node_archive_unusable"
    assert not (tmp_path / "installed").exists()

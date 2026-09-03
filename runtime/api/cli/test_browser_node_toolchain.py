"""Tests for the machine-local Node toolchain the Browser QA runtime runs on."""

from __future__ import annotations

import hashlib
import os
import tarfile
from pathlib import Path

import pytest

from yoke_cli import browser_node_toolchain as toolchain_module
from yoke_cli import resilient_fetch
from yoke_cli.browser_node_toolchain import (
    MANAGED_NODE_VERSION,
    NodeToolchain,
    NodeToolchainError,
    ensure_node_toolchain,
    managed_version_dir,
    platform_archive_slug,
    resolve_node_toolchain,
    toolchain_status,
)


NODE_SCRIPT = "#!/bin/sh\necho {version}\n"


@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch):
    """A transport retry must not spend its real 15s/60s backoff in a test."""
    monkeypatch.setattr(resilient_fetch, "sleep", lambda _seconds: None)


@pytest.fixture(autouse=True)
def machine_home(tmp_path, monkeypatch):
    """Anchor the machine home so no test reads or writes the real one."""
    home = tmp_path / "machine-home"
    home.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def _write_node_bin(bin_dir: Path, version: str) -> None:
    """Write an executable stand-in for node plus its npm and npx siblings."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    node = bin_dir / "node"
    node.write_text(NODE_SCRIPT.format(version=version), encoding="utf-8")
    node.chmod(0o755)
    for name in ("npm", "npx"):
        sibling = bin_dir / name
        sibling.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        sibling.chmod(0o755)


def _put_on_path(monkeypatch, bin_dir: Path) -> None:
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")


def _isolate_path(monkeypatch, tmp_path: Path) -> None:
    """A PATH with no node at all — the clean-host baseline."""
    empty = tmp_path / "empty-bin"
    empty.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty))


def _publish_release(
    releases: Path, version: str, slug: str, *, node_version: str
) -> str:
    """Build one release archive and pin its digest; return its base URL."""
    staging = releases / f"node-{version}-{slug}"
    _write_node_bin(staging / "bin", node_version)
    archive_dir = releases / version
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"node-{version}-{slug}.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(staging, arcname=staging.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    toolchain_module._ARCHIVE_SHA256[slug] = digest
    return releases.as_uri()


@pytest.fixture
def published_release(tmp_path, monkeypatch):
    """A file:// Node release whose digest is pinned for the run."""
    slug = platform_archive_slug()
    original = toolchain_module._ARCHIVE_SHA256[slug]
    base_url = _publish_release(
        tmp_path / "releases", MANAGED_NODE_VERSION, slug, node_version="v24.20.0"
    )
    yield base_url
    toolchain_module._ARCHIVE_SHA256[slug] = original


class TestPlatformSelection:
    def test_this_host_maps_to_a_published_archive(self):
        assert platform_archive_slug() in toolchain_module._ARCHIVE_SHA256

    def test_known_hosts_map_to_their_published_archives(self):
        assert platform_archive_slug("Darwin", "arm64") == "darwin-arm64"
        assert platform_archive_slug("Linux", "x86_64") == "linux-x64"
        assert platform_archive_slug("Linux", "aarch64") == "linux-arm64"

    def test_unsupported_host_names_its_code_and_recovery(self):
        with pytest.raises(NodeToolchainError) as raised:
            platform_archive_slug("Windows", "amd64")

        assert raised.value.code == "node_platform_unsupported"
        assert "install Node.js" in raised.value.recovery
        assert "windows/amd64" in raised.value.reason


class TestResolution:
    def test_a_supported_node_on_path_is_used_without_provisioning(
        self, tmp_path, monkeypatch
    ):
        bin_dir = tmp_path / "host-bin"
        _write_node_bin(bin_dir, "v20.11.0")
        _put_on_path(monkeypatch, bin_dir)

        resolved = resolve_node_toolchain()

        assert resolved == NodeToolchain(
            bin_dir=bin_dir, version="v20.11.0", source="host_path"
        )

    def test_a_node_below_the_floor_is_not_used(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "old-bin"
        _write_node_bin(bin_dir, "v16.20.0")
        _put_on_path(monkeypatch, bin_dir)

        assert resolve_node_toolchain() is None

    def test_a_provisioned_toolchain_resolves_without_a_node_on_path(
        self, tmp_path, monkeypatch
    ):
        _isolate_path(monkeypatch, tmp_path)
        _write_node_bin(managed_version_dir() / "bin", "v24.20.0")

        resolved = resolve_node_toolchain()

        assert resolved is not None
        assert resolved.source == "managed"
        assert resolved.bin_dir == managed_version_dir() / "bin"

    def test_a_clean_host_resolves_nothing_yet(self, tmp_path, monkeypatch):
        _isolate_path(monkeypatch, tmp_path)

        assert resolve_node_toolchain() is None

    def test_status_reports_the_missing_toolchain_and_the_pinned_version(
        self, tmp_path, monkeypatch
    ):
        _isolate_path(monkeypatch, tmp_path)

        status = toolchain_status()

        assert status["ok"] is False
        assert status["status"] == "missing"
        assert status["source"] == "none"
        assert status["managed_version"] == MANAGED_NODE_VERSION


class TestProvisioning:
    def test_a_clean_host_provisions_the_pinned_release(
        self, tmp_path, monkeypatch, published_release
    ):
        _isolate_path(monkeypatch, tmp_path)
        lines: list[str] = []

        toolchain = ensure_node_toolchain(base_url=published_release, emit=lines.append)

        assert toolchain.source == "managed"
        assert toolchain.version == "v24.20.0"
        assert toolchain.node.is_file()
        assert toolchain.npm.exists() and toolchain.npx.exists()
        assert any("checksum verified" in line for line in lines)

    def test_a_rerun_reuses_the_provisioned_toolchain(
        self, tmp_path, monkeypatch, published_release
    ):
        _isolate_path(monkeypatch, tmp_path)
        first = ensure_node_toolchain(base_url=published_release)

        def refuse(*_args, **_kwargs):
            raise AssertionError("a rerun must not fetch the release again")

        monkeypatch.setattr(toolchain_module, "fetch_file", refuse)
        second = ensure_node_toolchain(base_url=published_release)

        assert second == first
        assert toolchain_status()["source"] == "managed"

    def test_a_tampered_archive_refuses_before_it_is_unpacked(
        self, tmp_path, monkeypatch, published_release
    ):
        _isolate_path(monkeypatch, tmp_path)
        slug = platform_archive_slug()
        toolchain_module._ARCHIVE_SHA256[slug] = "0" * 64

        with pytest.raises(NodeToolchainError) as raised:
            ensure_node_toolchain(base_url=published_release)

        assert raised.value.code == "node_archive_digest_mismatch"
        assert "pinned digest" in raised.value.recovery
        assert not managed_version_dir().exists()

    def test_an_unreachable_release_names_the_dist_host_and_recovery(
        self, tmp_path, monkeypatch, published_release
    ):
        _isolate_path(monkeypatch, tmp_path)
        missing = (tmp_path / "no-such-release").as_uri()

        with pytest.raises(NodeToolchainError) as raised:
            ensure_node_toolchain(base_url=missing)

        assert raised.value.code == "node_download_failed"
        assert "nodejs.org/dist" in raised.value.recovery
        assert "yoke qa browser setup" in raised.value.recovery

    def test_an_unexpected_archive_layout_names_its_code(
        self, tmp_path, monkeypatch
    ):
        _isolate_path(monkeypatch, tmp_path)
        slug = platform_archive_slug()
        original = toolchain_module._ARCHIVE_SHA256[slug]
        releases = tmp_path / "flat-releases"
        archive_dir = releases / MANAGED_NODE_VERSION
        archive_dir.mkdir(parents=True)
        loose = tmp_path / "README"
        loose.write_text("not a release\n", encoding="utf-8")
        archive = archive_dir / f"node-{MANAGED_NODE_VERSION}-{slug}.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(loose, arcname="README")
        toolchain_module._ARCHIVE_SHA256[slug] = hashlib.sha256(
            archive.read_bytes()
        ).hexdigest()
        try:
            with pytest.raises(NodeToolchainError) as raised:
                ensure_node_toolchain(base_url=releases.as_uri())
        finally:
            toolchain_module._ARCHIVE_SHA256[slug] = original

        assert raised.value.code == "node_archive_unusable"


class TestCommandEnvironment:
    def test_the_toolchain_bin_dir_leads_path_for_spawned_node_processes(self):
        toolchain = NodeToolchain(
            bin_dir=Path("/machine/node/bin"), version="v24.20.0", source="managed"
        )

        env = toolchain.command_env({"PATH": f"/usr/bin{os.pathsep}/machine/node/bin"})

        assert env["PATH"].split(os.pathsep) == ["/machine/node/bin", "/usr/bin"]

    def test_an_empty_path_still_finds_the_toolchain(self):
        toolchain = NodeToolchain(
            bin_dir=Path("/machine/node/bin"), version="v24.20.0", source="managed"
        )

        assert toolchain.command_env({"PATH": ""})["PATH"] == "/machine/node/bin"

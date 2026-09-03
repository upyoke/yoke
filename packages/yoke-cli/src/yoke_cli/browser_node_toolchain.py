"""Machine-local Node.js toolchain for the Browser QA runtime.

Browser QA runs a Node daemon, and a genuinely clean host has no Node at all.
Treating Node as a host prerequisite made the supported recovery path depend
on developer-machine knowledge: a fresh Mac with no Homebrew was told to
install Homebrew first, and browser setup stopped before it materialized
anything. So this module owns the toolchain instead of asking for one.

Resolution order, cheapest first: a Node 18+ with npm already on ``PATH``, so
an equipped host downloads nothing; else the pinned release already unpacked
under ``~/.yoke/node/<version>/``, so a rerun of setup is a directory probe;
else a checksum-verified download of that release.

The managed toolchain lives beside the machine runtime rather than inside
``~/.yoke/browser-runtime`` because the browser tree is re-copied whenever its
packaged source hash changes, and a whole Node distribution has no business
being rebuilt with it. The per-version directory means a version bump unpacks
side by side instead of clobbering the toolchain a running daemon executes
from. Every refusal names a code, what happened, and the operator action that
clears it, because "Node is required" is the message that sent a person to a
package manager they did not have.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from yoke_cli.config import machine_config
from yoke_cli.resilient_fetch import FetchError, FetchVerificationError, fetch_file


#: The one pinned Node.js release this product provisions when a host has no
#: usable Node. Bumping it means replacing the digests below in the same
#: change; a digest that does not match the published archive fails the
#: install loudly rather than running unverified bytes.
MANAGED_NODE_VERSION = "v24.20.0"

#: The oldest Node major the browser runtime's package.json declares.
MINIMUM_NODE_MAJOR = 18

NODE_DIST_BASE_URL = "https://nodejs.org/dist"

#: Directory under the machine home holding provisioned toolchains, one
#: subdirectory per version.
NODE_DIR_NAME = "node"

HOST_PATH_SOURCE = "host_path"
MANAGED_SOURCE = "managed"

_FETCH_TIMEOUT_S = 300

#: (platform.system().lower(), platform.machine().lower()) -> release slug.
_PLATFORM_ARCHIVES = {
    ("darwin", "arm64"): "darwin-arm64",
    ("darwin", "x86_64"): "darwin-x64",
    ("linux", "aarch64"): "linux-arm64",
    ("linux", "arm64"): "linux-arm64",
    ("linux", "x86_64"): "linux-x64",
}

#: Published sha256 of each ``node-<version>-<slug>.tar.gz`` archive.
_ARCHIVE_SHA256 = {
    "darwin-arm64": "40e5607e5ecb3db9192723776da2d75d966260fc74a7a9e731c1bd67dda96bc8",
    "darwin-x64": "9e5b2644cf107befb6aefca676b96d3296bc10138096f022ed378d6233ed81f4",
    "linux-arm64": "3515603e2487879a39bc75716f1a2affd027500c64ba50e845cf72cb33219013",
    "linux-x64": "855d581f8a4eb1a8117e3426de25fe02770592febcfb31369aee1ffbfee9e8ec",
}

PLATFORM_UNSUPPORTED_CODE = "node_platform_unsupported"
DOWNLOAD_FAILED_CODE = "node_download_failed"
DIGEST_MISMATCH_CODE = "node_archive_digest_mismatch"
ARCHIVE_UNUSABLE_CODE = "node_archive_unusable"
PROVISIONED_UNUSABLE_CODE = "node_provisioned_but_unusable"


class NodeToolchainError(RuntimeError):
    """The Browser QA Node toolchain could not be resolved or provisioned."""

    def __init__(self, reason: str, *, code: str, recovery: str) -> None:
        super().__init__(f"{reason} Recovery: {recovery}")
        self.code = code
        self.reason = reason
        self.recovery = recovery


@dataclass(frozen=True)
class NodeToolchain:
    """One resolved Node, npm, and npx the browser runtime executes with."""

    bin_dir: Path
    version: str
    source: str

    @property
    def node(self) -> Path:
        return self.bin_dir / "node"

    @property
    def npm(self) -> Path:
        return self.bin_dir / "npm"

    @property
    def npx(self) -> Path:
        return self.bin_dir / "npx"

    def command_env(self, base: Optional[Mapping[str, str]] = None) -> dict[str, str]:
        """Environment whose ``PATH`` finds this toolchain first.

        npm and npx are ``#!/usr/bin/env node`` scripts, and Playwright spawns
        further Node processes of its own, so invoking them by absolute path
        is not enough — the interpreter they resolve has to be this
        toolchain's, not whatever the host happens to expose.
        """
        env = dict(os.environ if base is None else base)
        bin_dir = str(self.bin_dir)
        rest = [
            entry
            for entry in env.get("PATH", "").split(os.pathsep)
            if entry and entry != bin_dir
        ]
        env["PATH"] = os.pathsep.join([bin_dir, *rest])
        return env


def platform_archive_slug(
    system: Optional[str] = None, machine: Optional[str] = None
) -> str:
    """Map this host to a published Node archive slug, or refuse."""
    system_name = (system or platform.system()).lower()
    machine_name = (machine or platform.machine()).lower()
    slug = _PLATFORM_ARCHIVES.get((system_name, machine_name))
    if slug is None:
        raise NodeToolchainError(
            "Browser QA provisions Node.js only for "
            f"{', '.join(sorted(set(_PLATFORM_ARCHIVES.values())))}, and this "
            f"host reports {system_name}/{machine_name}.",
            code=PLATFORM_UNSUPPORTED_CODE,
            recovery=(
                f"install Node.js {MINIMUM_NODE_MAJOR}+ and npm for this "
                "platform yourself, then rerun `yoke qa browser setup`"
            ),
        )
    return slug


def managed_root() -> Path:
    return machine_config.yoke_home() / NODE_DIR_NAME


def managed_version_dir(version: str = MANAGED_NODE_VERSION) -> Path:
    return managed_root() / version


def resolve_node_toolchain(
    version: str = MANAGED_NODE_VERSION,
) -> Optional[NodeToolchain]:
    """The toolchain this host would run today, without provisioning one."""
    host = _host_toolchain()
    if host is not None:
        return host
    return _toolchain_at(managed_version_dir(version) / "bin", MANAGED_SOURCE)


def ensure_node_toolchain(
    version: str = MANAGED_NODE_VERSION,
    *,
    base_url: str = NODE_DIST_BASE_URL,
    emit: Callable[[str], None] = lambda _line: None,
) -> NodeToolchain:
    """Resolve a usable toolchain, provisioning the pinned release if needed."""
    resolved = resolve_node_toolchain(version)
    if resolved is not None:
        return resolved
    return provision_managed_toolchain(version, base_url=base_url, emit=emit)


def provision_managed_toolchain(
    version: str = MANAGED_NODE_VERSION,
    *,
    base_url: str = NODE_DIST_BASE_URL,
    emit: Callable[[str], None] = lambda _line: None,
) -> NodeToolchain:
    """Download, verify, and unpack one pinned Node release for this host."""
    slug = platform_archive_slug()
    name = f"node-{version}-{slug}.tar.gz"
    url = f"{base_url}/{version}/{name}"
    destination = managed_version_dir(version)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".fetch-", dir=destination.parent))
    try:
        archive = staging / name
        emit(f"  [browser-node] fetching {url}")
        _download(url, archive, expected_sha256=_ARCHIVE_SHA256[slug])
        emit("  [browser-node] checksum verified; unpacking")
        _unpack(archive, staging, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    toolchain = _toolchain_at(destination / "bin", MANAGED_SOURCE)
    if toolchain is None:
        raise NodeToolchainError(
            f"the unpacked Node {version} release under {destination} did not "
            "provide a working node and npm.",
            code=PROVISIONED_UNUSABLE_CODE,
            recovery=(
                f"remove {destination} and rerun `yoke qa browser setup`; if it "
                f"recurs, install Node.js {MINIMUM_NODE_MAJOR}+ and npm on "
                "this host"
            ),
        )
    emit(f"  [browser-node] installed {version} at {destination}")
    return toolchain


def toolchain_status(version: str = MANAGED_NODE_VERSION) -> dict[str, object]:
    """Readiness facts for ``yoke qa browser status``."""
    found = resolve_node_toolchain(version)
    return {
        "ok": found is not None,
        "status": "ready" if found is not None else "missing",
        "source": found.source if found is not None else "none",
        "version": found.version if found is not None else None,
        "managed_version": version,
        "bin_dir": str(found.bin_dir) if found is not None else None,
    }


def _host_toolchain() -> Optional[NodeToolchain]:
    """A Node 18+ with npm already on ``PATH``, or None."""
    node = shutil.which("node")
    if node is None or shutil.which("npm") is None:
        return None
    return _toolchain_at(Path(node).parent, HOST_PATH_SOURCE)


def _toolchain_at(bin_dir: Path, source: str) -> Optional[NodeToolchain]:
    """Report the toolchain in *bin_dir* when its node and npm both work."""
    node = bin_dir / "node"
    if not node.is_file() or not (bin_dir / "npm").exists():
        return None
    version = _node_version(node)
    if version is None:
        return None
    return NodeToolchain(bin_dir=bin_dir, version=version, source=source)


def _node_version(node: Path) -> Optional[str]:
    """The reported version when *node* runs and satisfies the floor."""
    try:
        result = subprocess.run(
            [str(node), "--version"], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    # An uncaptured run reports no stdout; that is "no version", not a crash.
    version = (result.stdout or "").strip()
    if result.returncode != 0 or not version:
        return None
    major = version.lstrip("v").split(".", 1)[0]
    if not major.isdigit() or int(major) < MINIMUM_NODE_MAJOR:
        return None
    return version


def _download(url: str, destination: Path, *, expected_sha256: str) -> None:
    try:
        fetch_file(
            url, destination, timeout=_FETCH_TIMEOUT_S, expected_sha256=expected_sha256
        )
    except FetchVerificationError as exc:
        raise NodeToolchainError(
            f"the downloaded Node.js release did not match its pinned "
            f"checksum: {exc}",
            code=DIGEST_MISMATCH_CODE,
            recovery=(
                "nothing was installed; rerun `yoke qa browser setup` in case "
                "the transfer was corrupted. A repeat means this build's "
                "pinned digest no longer matches the published release, and "
                "the pin has to be corrected rather than bypassed"
            ),
        ) from exc
    except FetchError as exc:
        raise NodeToolchainError(
            f"the pinned Node.js release could not be fetched: {exc}",
            code=DOWNLOAD_FAILED_CODE,
            recovery=(
                f"confirm this host can reach {NODE_DIST_BASE_URL} (proxy, "
                "firewall, or offline runner), then rerun `yoke qa browser "
                "setup`; an air-gapped host needs Node.js "
                f"{MINIMUM_NODE_MAJOR}+ and npm installed by hand"
            ),
        ) from exc


def _unpack(archive: Path, staging: Path, destination: Path) -> None:
    """Extract the release and move its single top-level directory into place."""
    extract_root = staging / "extracted"
    extract_root.mkdir()
    try:
        with tarfile.open(archive, "r:gz") as handle:
            # "tar" filter: blocks absolute paths and parent escapes while
            # preserving the executable modes node and npm need.
            handle.extractall(extract_root, filter="tar")
    except (tarfile.TarError, OSError) as exc:
        raise NodeToolchainError(
            f"the downloaded Node.js archive could not be unpacked: {exc}",
            code=ARCHIVE_UNUSABLE_CODE,
            recovery=(
                "confirm there is free space and write access under "
                f"{destination.parent}, then rerun `yoke qa browser setup`"
            ),
        ) from exc
    entries = list(extract_root.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise NodeToolchainError(
            f"the downloaded Node.js archive held {[e.name for e in entries]} "
            "instead of one top-level directory.",
            code=ARCHIVE_UNUSABLE_CODE,
            recovery=(
                "rerun `yoke qa browser setup` to fetch the release again; a "
                "persistent mismatch means the pinned release changed shape "
                "and this product needs a new pin"
            ),
        )
    if destination.exists():
        shutil.rmtree(destination)
    entries[0].replace(destination)


__all__ = [
    "MANAGED_NODE_VERSION",
    "MINIMUM_NODE_MAJOR",
    "NODE_DIST_BASE_URL",
    "NodeToolchain",
    "NodeToolchainError",
    "ensure_node_toolchain",
    "managed_version_dir",
    "platform_archive_slug",
    "provision_managed_toolchain",
    "resolve_node_toolchain",
    "toolchain_status",
]

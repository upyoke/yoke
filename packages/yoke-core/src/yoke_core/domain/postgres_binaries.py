"""Embedded PostgreSQL binaries for the local-mode engine.

Local mode runs Postgres from per-target binaries kept under the machine
runtime dir (``~/.yoke/postgres/<version>/``), never from a system
install. Resolution order: already-fetched binaries under that directory,
else a lazy fetch from the theseus-rs/postgresql-binaries GitHub releases
(one self-contained tarball per ``<version>-<target>`` with a sha256
companion asset, verified before unpack).

One Postgres version is pinned here (:data:`POSTGRES_VERSION`); the
per-version directory layout means a future version bump fetches
side-by-side rather than clobbering a running cluster's binaries.

Tests never hit the network: the cluster lifecycle accepts any
``bin_dir`` (system binaries from ``PATH`` via ``bin_dir=None``), and
:func:`fetch_binaries` accepts a ``base_url`` override (``file://``
fixture releases).
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from yoke_contracts.machine_config import runtime as machine_runtime

#: The one pinned embedded-engine Postgres version (theseus-rs release tag:
#: upstream major.minor plus a build suffix).
POSTGRES_VERSION = "17.10.0"

RELEASE_BASE_URL = (
    "https://github.com/theseus-rs/postgresql-binaries/releases/download"
)

#: Directory under the machine runtime dir holding fetched engines,
#: one subdirectory per version.
BINARIES_DIR_NAME = "postgres"

_FETCH_TIMEOUT_S = 120
_CHUNK_BYTES = 1 << 20

#: (sys.platform prefix, platform.machine()) -> release target triple.
_PLATFORM_TARGETS = {
    ("darwin", "arm64"): "aarch64-apple-darwin",
    ("darwin", "x86_64"): "x86_64-apple-darwin",
    ("linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("linux", "arm64"): "aarch64-unknown-linux-gnu",
    ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
}


class PostgresBinariesError(RuntimeError):
    """Embedded Postgres binaries could not be resolved or fetched."""


def platform_target(
    system: Optional[str] = None, machine: Optional[str] = None,
) -> str:
    """Map this host to a release target triple, or raise."""
    sys_name = (system or platform.system()).lower()
    machine_name = (machine or platform.machine()).lower()
    target = _PLATFORM_TARGETS.get((sys_name, machine_name))
    if target is None:
        raise PostgresBinariesError(
            f"no embedded Postgres binaries are published for "
            f"{sys_name}/{machine_name}; supported targets: "
            + ", ".join(sorted(set(_PLATFORM_TARGETS.values())))
        )
    return target


def release_asset_name(version: str, target: str) -> str:
    return f"postgresql-{version}-{target}.tar.gz"


def release_asset_url(
    version: str, target: str, *, base_url: str = RELEASE_BASE_URL,
) -> str:
    return f"{base_url}/{version}/{release_asset_name(version, target)}"


def binaries_root() -> Path:
    return machine_runtime.yoke_home() / BINARIES_DIR_NAME


def version_dir(version: str = POSTGRES_VERSION) -> Path:
    return binaries_root() / version


def installed_bin_dir(version: str = POSTGRES_VERSION) -> Optional[Path]:
    """The fetched bin directory for *version*, or None when absent."""
    candidate = version_dir(version) / "bin"
    if (candidate / "initdb").is_file():
        return candidate
    return None


def ensure_binaries(
    version: str = POSTGRES_VERSION,
    *,
    base_url: str = RELEASE_BASE_URL,
    emit: Callable[[str], None] = lambda _line: None,
) -> Path:
    """Return the engine bin directory, fetching lazily on first use."""
    existing = installed_bin_dir(version)
    if existing is not None:
        return existing
    return fetch_binaries(version, base_url=base_url, emit=emit)


def fetch_binaries(
    version: str = POSTGRES_VERSION,
    target: Optional[str] = None,
    *,
    base_url: str = RELEASE_BASE_URL,
    emit: Callable[[str], None] = lambda _line: None,
) -> Path:
    """Fetch, verify, and unpack one engine release; return its bin dir."""
    resolved_target = target or platform_target()
    url = release_asset_url(version, resolved_target, base_url=base_url)
    dest = version_dir(version)
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".fetch-", dir=dest.parent))
    try:
        tarball = staging / release_asset_name(version, resolved_target)
        emit(f"  [postgres-binaries] fetching {url}")
        _download(url, tarball)
        _verify_sha256(url, tarball)
        emit("  [postgres-binaries] checksum verified; unpacking")
        _unpack_release(tarball, staging, dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    bin_dir = installed_bin_dir(version)
    if bin_dir is None:
        raise PostgresBinariesError(
            f"fetched release did not provide bin/initdb under {dest}"
        )
    emit(f"  [postgres-binaries] installed {version} at {dest}")
    return bin_dir


def _download(url: str, dest: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_S) as response:
            with dest.open("wb") as out:
                shutil.copyfileobj(response, out, _CHUNK_BYTES)
    except OSError as exc:
        raise PostgresBinariesError(f"fetch failed for {url}: {exc}") from exc


def _verify_sha256(url: str, tarball: Path) -> None:
    """Verify the tarball against its published ``.sha256`` companion."""
    checksum_url = f"{url}.sha256"
    try:
        with urllib.request.urlopen(
            checksum_url, timeout=_FETCH_TIMEOUT_S,
        ) as response:
            published = response.read().decode("utf-8").split()[0].strip().lower()
    except (OSError, IndexError) as exc:
        raise PostgresBinariesError(
            f"checksum fetch failed for {checksum_url}: {exc}"
        ) from exc
    digest = hashlib.sha256()
    with tarball.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != published:
        raise PostgresBinariesError(
            f"checksum mismatch for {tarball.name}: "
            f"published {published}, fetched content {actual}"
        )


def _unpack_release(tarball: Path, staging: Path, dest: Path) -> None:
    """Extract the release and move its single top-level dir into place."""
    extract_root = staging / "extracted"
    extract_root.mkdir()
    try:
        with tarfile.open(tarball, "r:gz") as archive:
            # "tar" filter: blocks absolute paths / parent escapes while
            # preserving the executable modes the engine binaries need.
            archive.extractall(extract_root, filter="tar")
    except (tarfile.TarError, OSError) as exc:
        raise PostgresBinariesError(f"unpack failed for {tarball.name}: {exc}") from exc
    entries = [entry for entry in extract_root.iterdir()]
    if len(entries) != 1 or not entries[0].is_dir():
        raise PostgresBinariesError(
            f"unexpected release layout in {tarball.name}: expected one "
            f"top-level directory, found {[e.name for e in entries]}"
        )
    if dest.exists():
        shutil.rmtree(dest)
    entries[0].replace(dest)


__all__ = [
    "BINARIES_DIR_NAME",
    "POSTGRES_VERSION",
    "PostgresBinariesError",
    "RELEASE_BASE_URL",
    "binaries_root",
    "ensure_binaries",
    "fetch_binaries",
    "installed_bin_dir",
    "platform_target",
    "release_asset_name",
    "release_asset_url",
    "version_dir",
]

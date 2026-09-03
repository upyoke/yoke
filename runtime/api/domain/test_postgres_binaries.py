"""Tests for the embedded Postgres binary resolver.

Network-free: fetch tests serve a fixture release over ``file://`` via
the ``base_url`` override; resolution tests use pre-populated machine
runtime dirs.
"""

from __future__ import annotations

import hashlib
import tarfile
import urllib.error
from pathlib import Path

import pytest

from yoke_core.domain import postgres_binaries as pb
from yoke_cli import resilient_fetch


@pytest.fixture(autouse=True)
def _isolated_machine_home(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))


def test_platform_target_mapping():
    assert pb.platform_target("Darwin", "arm64") == "aarch64-apple-darwin"
    assert pb.platform_target("Darwin", "x86_64") == "x86_64-apple-darwin"
    assert pb.platform_target("Linux", "x86_64") == "x86_64-unknown-linux-gnu"
    assert pb.platform_target("Linux", "aarch64") == "aarch64-unknown-linux-gnu"


def test_platform_target_unsupported_names_host():
    with pytest.raises(pb.PostgresBinariesError, match="sunos/sparc"):
        pb.platform_target("SunOS", "sparc")


def test_release_asset_url_shape():
    url = pb.release_asset_url("17.10.0", "aarch64-apple-darwin")
    assert url == (
        "https://github.com/theseus-rs/postgresql-binaries/releases/download"
        "/17.10.0/postgresql-17.10.0-aarch64-apple-darwin.tar.gz"
    )


def test_paths_resolve_under_machine_runtime_dir(tmp_path):
    assert pb.binaries_root() == tmp_path / "machine-home" / "postgres"
    assert pb.version_dir("1.2.3") == tmp_path / "machine-home" / "postgres" / "1.2.3"


def test_installed_bin_dir_requires_initdb(tmp_path):
    assert pb.installed_bin_dir("1.2.3") is None
    bin_dir = pb.version_dir("1.2.3") / "bin"
    bin_dir.mkdir(parents=True)
    assert pb.installed_bin_dir("1.2.3") is None  # dir alone is not enough
    (bin_dir / "initdb").write_text("#!/bin/sh\n", encoding="utf-8")
    assert pb.installed_bin_dir("1.2.3") == bin_dir


def test_ensure_binaries_short_circuits_without_fetch(monkeypatch):
    bin_dir = pb.version_dir("1.2.3") / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "initdb").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        pb, "fetch_binaries",
        lambda *a, **kw: pytest.fail("installed binaries must not refetch"),
    )

    assert pb.ensure_binaries("1.2.3") == bin_dir


def _fixture_release(
    releases_root: Path, version: str, target: str, *, corrupt_checksum: bool = False,
) -> str:
    """Build a file:// release mirroring the published tarball layout."""
    release_dir = releases_root / version
    release_dir.mkdir(parents=True)
    payload_root = releases_root / f"payload-{version}"
    inner = payload_root / f"postgresql-{version}-{target}"
    (inner / "bin").mkdir(parents=True)
    initdb = inner / "bin" / "initdb"
    initdb.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    initdb.chmod(0o755)
    (inner / "lib").mkdir()
    asset = release_dir / pb.release_asset_name(version, target)
    with tarfile.open(asset, "w:gz") as archive:
        archive.add(inner, arcname=inner.name)
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    if corrupt_checksum:
        digest = "0" * 64
    (release_dir / f"{asset.name}.sha256").write_text(
        f"{digest}  {asset.name}\n", encoding="utf-8"
    )
    return releases_root.as_uri()


def test_fetch_binaries_verifies_unpacks_and_installs(tmp_path):
    base_url = _fixture_release(tmp_path / "releases", "9.9.9", "aarch64-apple-darwin")

    bin_dir = pb.fetch_binaries("9.9.9", "aarch64-apple-darwin", base_url=base_url)

    assert bin_dir == pb.version_dir("9.9.9") / "bin"
    initdb = bin_dir / "initdb"
    assert initdb.is_file()
    assert initdb.stat().st_mode & 0o111  # exec bit survives unpack
    # No staging residue next to the installed version dir.
    residue = [
        entry.name
        for entry in pb.binaries_root().iterdir()
        if entry.name != "9.9.9"
    ]
    assert residue == []


def test_fetch_binaries_rejects_checksum_mismatch(tmp_path):
    base_url = _fixture_release(
        tmp_path / "releases", "9.9.9", "aarch64-apple-darwin",
        corrupt_checksum=True,
    )

    with pytest.raises(pb.PostgresBinariesError, match="sha256 .* does not match"):
        pb.fetch_binaries("9.9.9", "aarch64-apple-darwin", base_url=base_url)
    assert pb.installed_bin_dir("9.9.9") is None


def test_ensure_binaries_fetches_once_then_reuses(tmp_path, monkeypatch):
    base_url = _fixture_release(tmp_path / "releases", "9.9.9", "aarch64-apple-darwin")
    monkeypatch.setattr(pb, "platform_target", lambda *a, **kw: "aarch64-apple-darwin")

    first = pb.ensure_binaries("9.9.9", base_url=base_url)
    monkeypatch.setattr(
        pb, "fetch_binaries",
        lambda *a, **kw: pytest.fail("second ensure must reuse the install"),
    )
    second = pb.ensure_binaries("9.9.9", base_url=base_url)

    assert first == second == pb.version_dir("9.9.9") / "bin"


class _DownloadResponse:
    def __init__(self, body: bytes, *, content_length: int) -> None:
        self.body = body
        self.headers = {"Content-Length": str(content_length)}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, limit=None) -> bytes:
        return self.body if limit is None else self.body[:limit]


def test_download_retries_twice_and_returns_attempt_evidence(tmp_path, monkeypatch):
    url = "https://artifacts.example.test/postgres.tar.gz"
    body = b"complete tarball"
    effects = iter([
        urllib.error.URLError("connection dropped"),
        TimeoutError("timed out"),
        _DownloadResponse(body, content_length=len(body)),
    ])
    attempts = []

    def opener(request, *, timeout):
        attempts.append((request.full_url, timeout))
        effect = next(effects)
        if isinstance(effect, BaseException):
            raise effect
        return effect

    sleeps = []
    monkeypatch.setattr(resilient_fetch, "urlopen", opener)
    monkeypatch.setattr(resilient_fetch, "sleep", sleeps.append)

    result = pb._download(
        url,
        tmp_path / "postgres.tar.gz",
        expected_sha256=hashlib.sha256(body).hexdigest(),
    )

    assert result.attempts == 3
    assert len(attempts) == 3
    assert sleeps == [15.0, 60.0]


def test_download_permanent_failure_names_url_and_attempts(tmp_path, monkeypatch):
    url = "https://artifacts.example.test/missing.tar.gz"
    missing = urllib.error.HTTPError(url, 404, "missing", {}, None)
    calls = []

    def opener(*_args, **_kwargs):
        calls.append(1)
        raise missing

    monkeypatch.setattr(resilient_fetch, "urlopen", opener)
    monkeypatch.setattr(
        resilient_fetch,
        "sleep",
        lambda _seconds: pytest.fail("permanent failures must not back off"),
    )

    with pytest.raises(pb.PostgresBinariesError) as raised:
        pb._download(
            url, tmp_path / "missing.tar.gz", expected_sha256="0" * 64
        )

    assert url in str(raised.value)
    assert "1 attempt" in str(raised.value)
    assert calls == [1]


def test_download_rejects_truncated_tarball_before_publish(tmp_path, monkeypatch):
    url = "https://artifacts.example.test/truncated.tar.gz"
    body = b"truncated"
    monkeypatch.setattr(
        resilient_fetch,
        "urlopen",
        lambda *_args, **_kwargs: _DownloadResponse(body, content_length=500),
    )
    monkeypatch.setattr(
        resilient_fetch,
        "sleep",
        lambda _seconds: pytest.fail("verification failures must not back off"),
    )
    destination = tmp_path / "truncated.tar.gz"

    with pytest.raises(pb.PostgresBinariesError, match="Content-Length 500"):
        pb._download(
            url,
            destination,
            expected_sha256=hashlib.sha256(body).hexdigest(),
        )

    assert not destination.exists()

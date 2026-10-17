"""Golden archives cannot capture or roll back the live desktop browser profile."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile

import pytest

from yoke_harness.ssh_linux_baseline import _ARCHIVE_PROGRAM
from yoke_harness.ssh_linux_browser_sign_in import SNAP_CHROMIUM_HOME_ENTRY

pytestmark = pytest.mark.skipif(os.getuid() == 0, reason="owner-only archive")


def operation(home, golden, action):
    result = subprocess.run(
        [sys.executable, "-c", _ARCHIVE_PROGRAM, action, str(home), str(golden)],
        input="[]",
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
    )
    return result, json.loads(result.stdout.splitlines()[-1])


def profile(home, value):
    store = home / SNAP_CHROMIUM_HOME_ENTRY / "Default" / "Cookies"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(value)
    store.chmod(0o600)
    return store


def legacy_golden(golden):
    """Simulate the old golden that incorrectly captured browser cookies."""
    archive_path = golden / "home.tar.gz"
    with tarfile.open(archive_path) as archive:
        saved = [
            (member, archive.extractfile(member).read() if member.isfile() else None)
            for member in archive.getmembers()
        ]
    with tarfile.open(archive_path, "w:gz") as archive:
        for member, content in saved:
            archive.addfile(
                member, io.BytesIO(content) if content is not None else None
            )
        member = tarfile.TarInfo(SNAP_CHROMIUM_HOME_ENTRY + "/Default/Cookies")
        member.size = len(b"stale-golden-cookie")
        archive.addfile(member, io.BytesIO(b"stale-golden-cookie"))
    manifest_path = golden / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sha256"] = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


@pytest.fixture
def host(tmp_path):
    home, golden = tmp_path / "home", tmp_path / "golden"
    home.mkdir()
    (home / "settings").write_text("golden")
    return home, golden


def test_capture_excludes_profile_but_keeps_other_snap_state(host):
    home, golden = host
    profile(home, "live-cookie")
    other = home / "snap/chromium/common/preferences"
    other.write_text("ordinary state")
    result, evidence = operation(home, golden, "capture")
    assert result.returncode == 0, result.stderr + result.stdout
    with tarfile.open(golden / "home.tar.gz") as archive:
        assert not any(
            name.startswith(SNAP_CHROMIUM_HOME_ENTRY) for name in archive.getnames()
        )
        assert (
            archive.extractfile(str(other.relative_to(home))).read()
            == b"ordinary state"
        )
    assert SNAP_CHROMIUM_HOME_ENTRY in evidence["preserved_entries"]


@pytest.mark.parametrize("present", [True, False])
def test_reset_preserves_only_live_profile_and_ignores_old_golden_cookies(
    host, present
):
    home, golden = host
    assert operation(home, golden, "capture")[0].returncode == 0
    legacy_golden(golden)
    store = profile(home, "live-cookie") if present else home / SNAP_CHROMIUM_HOME_ENTRY
    (home / "settings").write_text("changed")
    for _ in range(2):
        result, evidence = operation(home, golden, "reset")
        assert result.returncode == 0, result.stderr + result.stdout
        assert (SNAP_CHROMIUM_HOME_ENTRY in evidence["preserved_entries"]) == present
        if present:
            assert store.read_text() == "live-cookie"
            assert store.stat().st_mode & 0o777 == 0o600
        else:
            assert not store.exists()
        assert (home / "settings").read_text() == "golden"


def test_unsafe_profile_parent_refuses_before_clearing(host, tmp_path):
    home, golden = host
    assert operation(home, golden, "capture")[0].returncode == 0
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / "snap").symlink_to(outside)
    (home / "settings").write_text("live")
    result, evidence = operation(home, golden, "reset")
    assert result.returncode != 0
    assert evidence["reason"] == "linux_browser_sign_in_store_unsafe"
    assert (home / "settings").read_text() == "live"

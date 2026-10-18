"""Native harness installs stay live while product installations reset."""

import hashlib
import io
import os
import json
import subprocess
import sys
import tarfile

import pytest

from runtime.api.domain.test_linux_browser_sign_in import operation
from yoke_harness.ssh_linux_baseline import _ARCHIVE_PROGRAM

pytestmark = pytest.mark.skipif(os.getuid() == 0, reason="owner-only archive")


@pytest.mark.parametrize(
    ("name", "target"),
    [
        ("claude", ".local/share/claude/versions/current"),
        ("codex", ".local/lib/node_modules/@openai/codex/bin/codex.js"),
        ("codex", ".codex/packages/app-server-daemon/releases/current/codex"),
        ("agent", ".local/share/cursor-agent/versions/current/agent"),
    ],
)
def test_capture_omits_install_and_reset_preserves_updated_binary(
    tmp_path, name, target
):
    home, golden = tmp_path / "home", tmp_path / "golden"
    binary, link = home / target, home / ".local/bin" / name
    binary.parent.mkdir(parents=True)
    binary.write_text("new executable")
    binary.chmod(0o755)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(binary)
    result, _ = operation(home, golden, "capture")
    assert result.returncode == 0, result.stdout + result.stderr
    with tarfile.open(golden / "home.tar.gz") as archive:
        saved = [
            (m, archive.extractfile(m).read() if m.isfile() else None)
            for m in archive.getmembers()
        ]
        assert target not in archive.getnames()
        assert str(link.relative_to(home)) not in archive.getnames()
    # A sealed older golden must not replace today's working harness install.
    with tarfile.open(golden / "home.tar.gz", "w:gz") as archive:
        for member, content in saved:
            archive.addfile(
                member, io.BytesIO(content) if content is not None else None
            )
        member = tarfile.TarInfo(target)
        member.size = 3
        archive.addfile(member, io.BytesIO(b"old"))
    manifest = golden / "manifest.json"
    data = json.loads(manifest.read_text())
    data["sha256"] = hashlib.sha256((golden / "home.tar.gz").read_bytes()).hexdigest()
    manifest.write_text(json.dumps(data))
    product = home / ".local/bin/yoke"
    product.write_text("must clear")
    result, evidence = operation(home, golden, "reset")
    assert result.returncode == 0, result.stdout + result.stderr
    assert binary.read_text() == "new executable"
    assert binary.stat().st_mode & 0o777 == 0o755
    assert link.is_symlink() and link.resolve() == binary
    assert str(link.relative_to(home)) in evidence["preserved_entries"]
    assert not product.exists()


def test_unsafe_install_link_refuses_without_clearing_home(tmp_path):
    home, golden = tmp_path / "home", tmp_path / "golden"
    home.mkdir()
    (home / "settings").write_text("golden")
    assert operation(home, golden, "capture")[0].returncode == 0
    link = home / ".local/bin/claude"
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp_path / "foreign")
    (home / "settings").write_text("live")
    result, evidence = operation(home, golden, "reset")
    assert result.returncode != 0
    assert evidence["reason"] == "linux_preserved_home_entry_unsafe"
    assert (home / "settings").read_text() == "live"


def test_archive_failure_carries_live_install_back(tmp_path):
    home, golden = tmp_path / "home", tmp_path / "golden"
    binary = home / ".local/share/claude/versions/current"
    binary.parent.mkdir(parents=True)
    binary.write_text("working install")
    assert operation(home, golden, "capture")[0].returncode == 0
    program = _ARCHIVE_PROGRAM.replace(
        'archive.extractall(home, members=members, filter="fully_trusted")',
        'raise OSError("restore interrupted")',
    )
    result = subprocess.run(
        [sys.executable, "-c", program, "reset", str(home), str(golden)],
        input="[]",
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
    )
    assert result.returncode != 0
    assert json.loads(result.stdout)["reason"] == "linux_golden_restore_failed"
    assert binary.read_text() == "working install"
    assert not list(tmp_path.glob("yoke-live-home-*"))

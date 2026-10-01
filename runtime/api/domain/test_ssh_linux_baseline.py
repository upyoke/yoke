"""Linux golden capture keeps persistent files and omits live socket state."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tarfile

import pytest

from yoke_harness.ssh_linux_baseline import ABSENT_HOME_PATHS, _ARCHIVE_PROGRAM


@pytest.mark.skipif(os.getuid() == 0, reason="capture requires a non-root test user")
def test_capture_filters_socket_types_and_resolved_links(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(home)
    (home / "credentials.sock").write_text("signed-in-state")
    (home / "safe.sock").symlink_to("credentials.sock")
    (home / "dangling").symlink_to("missing")
    (tmp_path / "outside").write_text("outside home")
    (home / "escaped").symlink_to("../outside")
    (home / "escaped-chain").symlink_to("escaped")
    (home / "nested").mkdir()
    (home / "nested/escaped").symlink_to("../../outside")
    (home / "socket-link").symlink_to("daemon")
    (home / "socket-chain").symlink_to("socket-link")
    golden = tmp_path / "golden"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as daemon:
        # Relative binding avoids the platform's Unix socket pathname limit.
        daemon.bind("daemon")
        result = subprocess.run(
            [sys.executable, "-c", _ARCHIVE_PROGRAM, "capture", str(home), str(golden)],
            input=json.dumps(ABSENT_HOME_PATHS),
            text=True,
            capture_output=True,
            env={**os.environ, "HOME": str(home)},
            check=False,
        )
    assert result.returncode == 0, result.stdout + result.stderr
    with tarfile.open(golden / "home.tar.gz") as archive:
        names = set(archive.getnames())
        assert {"credentials.sock", "safe.sock", "dangling", "nested"} <= names
        assert not names & {
            "daemon",
            "socket-link",
            "socket-chain",
            "escaped",
            "escaped-chain",
            "nested/escaped",
        }
        assert archive.extractfile("credentials.sock").read() == b"signed-in-state"
        assert archive.getmember("safe.sock").issym()

"""Each host adapter's file copy streams exact bytes or names its refusal.

The adapters' real reader scripts run on this machine in place of SSH, so
the checks cover the same shell text a Test Machine runs. The macOS reader
needs zsh; the Linux and Windows (WSL) reader needs GNU ``realpath``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain.ssh_linux_host_control import SshLinuxHostControl
from yoke_core.domain.ssh_mac_host_control import SshMacHostControl
from yoke_harness import remote_file_copy
from yoke_harness.remote_file_copy import HostCopyRefused, stream_remote_file

MAX_BYTES = 1024 * 1024
# Bytes that are not valid UTF-8, spanning several stream chunks.
PAYLOAD = bytes(range(256))[::-1] * 1200 + b"\xff\xfe\x00\x80"


def _gnu_realpath() -> bool:
    found = shutil.which("realpath")
    if found is None:
        return False
    return subprocess.run([found, "-m", "/x/y"], capture_output=True).returncode == 0


def _local(command: str) -> list[str]:
    return ["/bin/sh", "-c", command]


def _mac() -> SshMacHostControl:
    control = SshMacHostControl.__new__(SshMacHostControl)
    control.material = SimpleNamespace(secrets={})
    control._ssh_argv = _local
    return control


def _linux() -> SshLinuxHostControl:
    control = SshLinuxHostControl.__new__(SshLinuxHostControl)
    control.secret_values = ()
    control._ssh_argv = _local
    return control


ADAPTERS = [
    pytest.param(
        _mac,
        marks=pytest.mark.skipif(not Path("/bin/zsh").exists(), reason="needs zsh"),
        id="macos",
    ),
    pytest.param(
        _linux,
        marks=pytest.mark.skipif(not _gnu_realpath(), reason="needs GNU realpath"),
        id="linux",
    ),
]


@pytest.fixture(params=ADAPTERS)
def control(request):
    return request.param()


@pytest.fixture
def host(tmp_path):
    root = tmp_path / "host"
    (root / "scratch").mkdir(parents=True)
    (root / "evidence").mkdir()
    return root


def _copy(control, source, destination, *, refused_root, max_bytes=MAX_BYTES):
    return control.copy_file_to(
        str(source), destination, max_bytes=max_bytes, refused_root=str(refused_root)
    )


@pytest.mark.parametrize("payload", [PAYLOAD, b""], ids=["binary", "empty"])
def test_binary_file_round_trips_byte_equal(control, host, tmp_path, payload):
    source = host / "evidence" / "shot.png"
    source.write_bytes(payload)
    destination = tmp_path / "shot.png"
    written = _copy(control, source, destination, refused_root=host / "scratch")
    assert written == len(payload)
    assert destination.read_bytes() == payload
    assert sorted(p.name for p in tmp_path.iterdir()) == ["host", "shot.png"]


def _refusal(control, source, destination, **kwargs) -> HostCopyRefused:
    with pytest.raises(HostCopyRefused) as caught:
        _copy(control, source, destination, **kwargs)
    assert "Recovery: " in str(caught.value)
    return caught.value


def test_each_refusal_names_its_reason_and_keeps_the_destination(
    control, host, tmp_path
):
    destination = tmp_path / "kept.bin"
    destination.write_bytes(b"earlier copy")
    scratch = host / "scratch"
    (scratch / "token").write_text("secret")
    (host / "evidence" / "link").symlink_to(scratch / "token")
    (host / "evidence" / "big.bin").write_bytes(b"x" * 11)
    cases = {
        "host_copy_file_missing": host / "evidence" / "absent.png",
        "host_copy_not_a_file": host / "evidence",
        "host_copy_path_in_mission_scratch": scratch / "token",
        "host_copy_path_not_absolute": "evidence/shot.png",
    }
    for code, source in cases.items():
        refused = _refusal(control, source, destination, refused_root=scratch)
        assert refused.code == code
    linked = _refusal(
        control, host / "evidence" / "link", destination, refused_root=scratch
    )
    assert linked.code == "host_copy_path_in_mission_scratch"
    big = _refusal(
        control,
        host / "evidence" / "big.bin",
        destination,
        refused_root=scratch,
        max_bytes=10,
    )
    assert big.code == "host_copy_file_too_large"
    assert "10-byte QA artifact limit" in str(big)
    assert destination.read_bytes() == b"earlier copy"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["host", "kept.bin"]


def _stream(command: str, destination: Path, *, max_bytes: int = MAX_BYTES) -> int:
    return stream_remote_file(
        _local(command),
        destination,
        path="/remote/file",
        max_bytes=max_bytes,
        refused_root="/tmp/yoke-qa-mission",
    )


def test_stream_stops_at_the_bound_even_when_the_file_grows(tmp_path):
    destination = tmp_path / "out.bin"
    with pytest.raises(HostCopyRefused) as caught:
        _stream("head -c 400000 /dev/zero | base64", destination, max_bytes=1000)
    assert caught.value.code == "host_copy_file_too_large"
    assert list(tmp_path.iterdir()) == []


def test_damaged_stream_and_unknown_exit_are_named(tmp_path):
    destination = tmp_path / "out.bin"
    with pytest.raises(HostCopyRefused) as damaged:
        _stream("printf 'not base64!'", destination)
    assert damaged.value.code == "host_copy_transfer_failed"
    with pytest.raises(HostCopyRefused) as failed:
        _stream("echo connection reset >&2; exit 255", destination)
    assert failed.value.code == "host_copy_transfer_failed"
    assert "exit 255 (connection reset)" in str(failed.value)
    assert list(tmp_path.iterdir()) == []


def test_timeout_stops_the_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_file_copy, "COPY_TIMEOUT_SECONDS", 0.2)
    with pytest.raises(HostCopyRefused) as caught:
        _stream("exec sleep 5", tmp_path / "out.bin")
    assert caught.value.code == "host_copy_timed_out"
    assert list(tmp_path.iterdir()) == []


def test_unusable_destination_is_refused_before_connecting(tmp_path):
    for destination in (tmp_path / "missing" / "out.bin", tmp_path):
        with pytest.raises(HostCopyRefused) as caught:
            _stream("exit 99", destination)
        assert caught.value.code == "host_copy_destination_unavailable"

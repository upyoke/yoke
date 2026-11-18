"""Framed Windows stdin, including real Windows PowerShell with an open pipe."""

import base64
import hashlib
import subprocess

import pytest

from yoke_harness.native_windows import admin, provision
from yoke_harness.native_windows.stdin_frame import (
    MAX_BYTES,
    READ_FRAME_SCRIPT,
    frame_bytes,
    upload_received,
    upload_script,
)
from yoke_harness.native_windows.transport import WindowsTransport, encoded, quote
from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport


pytestmark = pytest.mark.windows


def test_frame_preserves_binary_and_rejects_oversized_payload(monkeypatch):
    from yoke_harness.native_windows import stdin_frame

    payload = bytes(range(256))
    header, body = frame_bytes(payload).split(":", 1)
    assert int(header, 16) == len(body)
    assert base64.b64decode(body, validate=True) == payload
    monkeypatch.setattr(stdin_frame, "MAX_BYTES", 2)
    with pytest.raises(ValueError, match="windows_stdin_frame_too_large"):
        frame_bytes(b"abc")


def test_receipt_requires_matching_digest_size_and_success():
    assert MAX_BYTES == 64 * 1024 * 1024
    assert upload_received(completed(receipt(b"abc")), b"abc")
    assert not upload_received(completed(receipt(b"abd")), b"abc")
    assert not upload_received(completed(receipt(b"abc"), 1), b"abc")
    assert not upload_received(completed("YOKE_UPLOAD:3:"), b"abc")
    # Upload commands must remain below cmd.exe's limit, including SSH wrappers.
    assert len(encoded(upload_script("'C:\\YokeQa\\test.ps1'"))) < 6000


def completed(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, "")


def receipt(payload):
    return f"YOKE_UPLOAD:{len(payload)}:{hashlib.sha256(payload).hexdigest()}"


@pytest.mark.parametrize(
    "payload", [b"", bytes(range(256)), " \n雪 secret \r\n ".encode()]
)
def test_frames_preserve_bytes_and_declare_encoded_size(payload):
    header, data = frame_bytes(payload).split(":", 1)
    assert len(header) == 8
    assert int(header, 16) == len(data)
    assert base64.b64decode(data, validate=True) == payload


def test_frame_size_bound_precedes_encoding(monkeypatch):
    from yoke_harness.native_windows import stdin_frame

    monkeypatch.setattr(stdin_frame, "MAX_BYTES", 2)
    with pytest.raises(ValueError, match="windows_stdin_frame_too_large"):
        frame_bytes(b"abc")
    assert MAX_BYTES < 2**31


def test_upload_receipt_requires_exact_content_and_success():
    payload = b"actual stored file"
    assert upload_received(completed(receipt(payload) + "\r\n"), payload)
    assert not upload_received(completed(receipt(b"other")), payload)
    assert not upload_received(completed("prefix" + receipt(payload)), payload)
    assert not upload_received(completed(receipt(payload), 1), payload)


def test_upload_reader_fits_small_command_transport():
    # Otherwise _upload_bytes would recursively stage its own upload reader.
    assert len(encoded(upload_script("'C:\\Users\\qa\\file.txt'"))) < 6000


@pytest.mark.parametrize("valid_receipt", [False, True])
def test_admin_upload_requires_receipt_and_password_stays_only_on_stdin(
    monkeypatch, valid_receipt
):
    script = "Write-Output 'ready'"
    password = " \nprivate雪\r\n "
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if len(calls) == 1:
            return completed(
                receipt(script.encode("utf-8-sig")) if valid_receipt else ""
            )
        return completed("ready")

    monkeypatch.setattr(provision.subprocess, "run", run)
    monkeypatch.setattr(admin, "run_framed", run)
    if valid_receipt:
        provision.admin_script("key", "host", "admin", script, input_text=password)
        assert calls[1][1]["input"] == frame_bytes(password.encode())
        assert len(calls) == 3
    else:
        with pytest.raises(RuntimeError, match="windows_admin_script_upload_failed"):
            provision.admin_script("key", "host", "admin", script, input_text=password)
        assert len(calls) == 2
    assert calls[0][1]["input"] == frame_bytes(script.encode("utf-8-sig"))
    assert all(password not in " ".join(argv) for argv, _ in calls)


@pytest.mark.parametrize("fail_chunk", [None, 1, 2])
def test_admin_upload_chunks_verify_whole_prefix_with_one_deadline(monkeypatch, fail_chunk):
    source = "Write-Output '雪';" * 400
    payload = source.encode("utf-8-sig")
    stored = bytearray()
    calls = []
    clock = [0]
    monkeypatch.setattr(admin.time, "monotonic", lambda: clock[0])

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        clock[0] += 1
        if "input" not in kwargs:
            assert "Remove-Item -LiteralPath" in base64.b64decode(argv[-1].split()[-1]).decode("utf-16-le")
            return completed()
        if "-EncodedCommand " not in argv[-1]:
            assert bytes(stored) == payload
            return completed("EXECUTED")
        script = base64.b64decode(argv[-1].split()[-1]).decode("utf-16-le")
        assert f"$file.Length -ne {len(stored)}" in script
        chunk = base64.b64decode(kwargs["input"].split(":", 1)[1], validate=True)
        assert len(chunk) <= 2048
        stored.extend(chunk)
        return completed(receipt(bytes(stored)) if len(calls) != fail_chunk else receipt(b"wrong"))

    monkeypatch.setattr(provision.subprocess, "run", run)
    monkeypatch.setattr(admin, "run_framed", run)
    if fail_chunk:
        with pytest.raises(RuntimeError, match="windows_admin_script_upload_failed"):
            provision.admin_script("key", "host", "admin", source)
        assert len(calls) == fail_chunk + 1
    else:
        assert provision.admin_script("key", "host", "admin", source).stdout == "EXECUTED"
        assert [kw["timeout"] for _, kw in calls[:-2]] == list(range(30, 30-len(calls)+2, -1))
        assert "CreateNew" in base64.b64decode(calls[0][0][-1].split()[-1]).decode("utf-16-le")


def test_admin_upload_never_resets_total_deadline(monkeypatch):
    clock = [0]
    monkeypatch.setattr(admin.time, "monotonic", lambda: clock[0])
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "input" not in kwargs:
            return completed()
        clock[0] = 31
        return completed(receipt(base64.b64decode(kwargs["input"].split(":", 1)[1])))

    monkeypatch.setattr(provision.subprocess, "run", run)
    monkeypatch.setattr(admin, "run_framed", run)
    with pytest.raises(admin.AdminScriptError) as error:
        provision.admin_script("key", "host", "admin", "x" * 5000)
    assert isinstance(error.value.__cause__, subprocess.TimeoutExpired)
    assert error.value.diagnostics["last_verified_offset"] == 2048
    assert error.value.diagnostics["cleanup"] == "verified_absent"
    assert len(calls) == 2  # first chunk and bounded owned-path cleanup


def test_failed_transport_upload_never_executes_script(monkeypatch):
    calls = []
    monkeypatch.setattr(
        SshTestMachineTransport,
        "_run",
        lambda self, script, **kw: calls.append(script) or completed(),
    )
    control = object.__new__(WindowsTransport)
    with pytest.raises(RuntimeError, match="length/hash receipt did not match"):
        control._run("Write-Output x;" * 1000)
    assert len(calls) == 2 and "Remove-Item" in calls[-1]
    assert not any(script.startswith("& ") for script in calls)


def test_file_upload_frames_binary_and_checks_receipt(monkeypatch):
    calls = []
    payload = bytes(range(256))
    control = object.__new__(WindowsTransport)
    monkeypatch.setattr(
        control,
        "_run",
        lambda script, **kw: calls.append((script, kw)) or completed(receipt(payload)),
    )
    assert control._upload_bytes(r"C:\YokeQa\file.bin", payload)
    assert calls[0][1]["input_text"] == frame_bytes(payload)


def test_ssh_bootstrap_uses_admin_ssh_without_azure_or_password_trimming(monkeypatch):
    scripts = []
    monkeypatch.setattr(provision, "test_machine_secret_path", lambda *a: "key")
    monkeypatch.setattr(
        provision, "read_test_machine_secret", lambda *a: " secret "
    )

    def run(argv, **kwargs):
        assert argv[0] == "ssh-keygen"
        return completed("ssh-ed25519 PUBLIC")

    def admin(key, host, user, script, **kwargs):
        scripts.append((script, kwargs))
        return completed("Native OpenSSH ready; password authentication disabled.")

    monkeypatch.setattr(provision.subprocess, "run", run)
    monkeypatch.setattr(provision, "admin_script", admin)
    provision.provision(
        "project", "machine", "host", "group", "admin", "qa", bootstrap_transport="ssh"
    )
    assert len(scripts) == 3
    assert scripts[1][1]["input_text"] == " secret "
    assert "Read-YokeFrame" in scripts[1][0]
    assert "ReadToEnd" not in scripts[1][0]
    assert ".Trim()" not in scripts[1][0]


@pytest.mark.windows_only(reason='requires native Windows PowerShell')
@pytest.mark.parametrize("payload", [b"", bytes(range(256)), " \r\n雪 \n ".encode()])
@pytest.mark.parametrize("mode", ["read", "upload"])
def test_native_reader_finishes_without_stdin_eof(payload, mode, tmp_path):
    destination = tmp_path / "uploaded.bin"
    script = (
        upload_script(quote(str(destination)))
        if mode == "upload"
        else READ_FRAME_SCRIPT
        + "\n[Console]::Out.Write([Convert]::ToBase64String((Read-YokeFrame)))"
    )
    child = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded(script),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        child.stdin.write(frame_bytes(payload).encode("ascii"))
        child.stdin.flush()
        # Deliberately do not close stdin until after process termination.
        assert child.wait(timeout=20) == 0
        output = child.stdout.read().decode()
        if mode == "upload":
            assert output.strip() == receipt(payload)
            assert destination.read_bytes() == payload
        else:
            assert output == base64.b64encode(payload).decode()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        child.stdin.close()
        child.stdout.close()
        child.stderr.close()


@pytest.mark.windows_only(reason='requires native Windows PowerShell')
@pytest.mark.parametrize(
    "frame",
    [
        b"badhead!:",
        b"ffffffff:",
        b"00000004:!!!!",
        b"00000004:YQ",
        b"00000004:YQ \n",
        b"00000004:YWJj",
    ],
)
def test_native_reader_rejects_bad_or_truncated_frames(frame):
    script = (
        "$ErrorActionPreference='Stop';"
        + READ_FRAME_SCRIPT.replace(str(MAX_BYTES), "2")
        + "\n$null=Read-YokeFrame; Write-Output 'ACCEPTED'"
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded(script),
        ],
        input=frame,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert b"ACCEPTED" not in result.stdout


def test_large_script_streams_utf8_bom_and_keeps_input(monkeypatch):
    from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport

    calls = []
    data = bytearray()

    def run(self, script, **kwargs):
        calls.append((script, kwargs))

        if "Read-YokeFrame" in script:
            chunk = base64.b64decode(kwargs["input_text"].split(":", 1)[1])
            assert len(chunk) <= 2048
            data.extend(chunk)
            return completed(receipt(data))
        return completed()

    monkeypatch.setattr(SshTestMachineTransport, "_run", run)
    control = object.__new__(WindowsTransport)
    source = 'Write-Output "héllo"; ' * 1000
    control._run(source, input_text="private-input", timeout=17)
    assert data.decode("utf-8-sig") == source
    assert calls[-2][1]["input_text"] == "private-input"
    assert calls[-2][0].startswith("& ")
    assert "Remove-Item" in calls[-1][0]


def test_staging_cleanup_failure_preserves_original_upload_failure(monkeypatch):
    def run(argv, **kwargs):
        if "input" in kwargs:
            return completed("wrong receipt")
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired(argv, 10)

    monkeypatch.setattr(provision.subprocess, "run", run)
    monkeypatch.setattr(admin, "run_framed", run)
    with pytest.raises(RuntimeError, match="windows_admin_script_upload_failed") as error:
        provision.admin_script("key", "host", "admin", "source")
    assert "Owned Windows staging cleanup failed" in error.value.__notes__[0]

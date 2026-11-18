"""SFTP staging must verify bytes and privacy before any administrator execution."""

import base64
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from yoke_contracts.owner_private_path import is_owner_private_file
from yoke_harness.native_windows import admin_staging as staging


ROOT = r"C:\ProgramData\YokeQaProvision-" + "1" * 32
SSH = ["ssh", "-F", "none", "-i", "private-key-path", "admin@host"]


def result(output="", code=0):
    return subprocess.CompletedProcess([], code, output, "private diagnostic")


def diagnostic():
    return {"steps": [], "remote_directory_owned": False, "last_verified_offset": 0}


@pytest.mark.parametrize("failure", [None, "prepare", "ownership", "sftp", "verification"])
def test_private_staging_refuses_transfer_or_verification_failure(monkeypatch, tmp_path, failure):
    tmp_path = tmp_path / "controller 雪"
    tmp_path.mkdir()
    payload = "Write-Output 'private script 雪'".encode("utf-8-sig")
    calls, sources = [], []
    clock = [0]
    original = FileNotFoundError("private SFTP cause")
    monkeypatch.setattr(staging.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(staging.time, "monotonic", lambda: clock[0])

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        clock[0] += 10
        assert payload.decode("utf-8-sig") not in " ".join(argv)
        if argv[0] == "sftp":
            assert kwargs["encoding"] == "utf-8"
            assert argv[1:-3] == SSH[1:-1]
            assert argv[-3:] == ["-b", "-", "admin@host"]
            batch = kwargs["input"]
            local = Path(batch.split('"')[1])
            sources.append(local)
            assert local.read_bytes() == payload
            assert is_owner_private_file(local)
            assert payload.decode("utf-8-sig") not in batch
            assert batch.endswith('" "/C:/ProgramData/YokeQaProvision-' + "1" * 32 + '/script.ps1"\n')
            if failure == "sftp":
                raise original
            return result()
        script = base64.b64decode(argv[-1].split()[-1]).decode("utf-16le")
        assert len(argv[-1]) < 8000
        if "YOKE_ADMIN_STAGE_OWNED" in script:
            return result("" if failure == "ownership" else "YOKE_ADMIN_STAGE_OWNED", 1 if failure == "prepare" else 0)
        assert "Get-FileHash" in script and str(len(payload)) in script
        return result("" if failure == "verification" else "YOKE_ADMIN_SCRIPT_VERIFIED")

    monkeypatch.setattr(staging.subprocess, "run", run)
    d = diagnostic()
    if failure:
        with pytest.raises((RuntimeError, FileNotFoundError)) as error:
            staging.stage_script(SSH, payload, ROOT, d, deadline=90)
        assert d["last_verified_offset"] == 0
        if failure == "sftp":
            assert error.value is original
    else:
        staging.stage_script(SSH, payload, ROOT, d, deadline=90)
        assert d["last_verified_offset"] == len(payload)
        assert [kw["timeout"] for _, kw in calls] == [90, 80, 70]
    assert d["local_cleanup"] == "verified_absent"
    assert not list(tmp_path.iterdir())
    assert all(not source.exists() for source in sources)
    assert not any(" -File " in argv[-1] for argv, _ in calls)


def test_staging_deadline_covers_all_steps(monkeypatch, tmp_path):
    clock, calls = [0], []
    monkeypatch.setattr(staging.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(staging.time, "monotonic", lambda: clock[0])

    def run(argv, **kwargs):
        calls.append(argv)
        clock[0] = 91
        return result("YOKE_ADMIN_STAGE_OWNED")

    monkeypatch.setattr(staging.subprocess, "run", run)
    d = diagnostic()
    with pytest.raises(subprocess.TimeoutExpired):
        staging.stage_script(SSH, b"script", ROOT, d, deadline=90)
    assert len(calls) == 1
    assert d["steps"][-1]["phase"] == "sftp"
    assert d["steps"][-1]["outcome"] == "TimeoutExpired"
    assert d["local_cleanup"] == "verified_absent"


def test_sftp_batch_paths_reject_controls_and_globs(monkeypatch, tmp_path):
    monkeypatch.setattr(staging.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(staging.subprocess, "run", lambda *a, **kw: pytest.fail("unsafe path reached network"))
    for suffix in ['\nother', '*', '?', '[x]', '"']:
        with pytest.raises(RuntimeError, match="windows_admin_sftp_path_invalid"):
            staging.stage_script(SSH, b"script", ROOT + suffix, diagnostic(), deadline=100)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("primary_fails", [False, True])
def test_local_cleanup_failure_preserves_primary(monkeypatch, tmp_path, primary_fails):
    monkeypatch.setattr(staging.tempfile, "gettempdir", lambda: str(tmp_path))
    primary = FileNotFoundError("private primary")
    cleanup = OSError("private cleanup")
    original_rmdir = Path.rmdir

    def rmdir(path):
        if path.name.startswith("yoke-admin-"):
            raise cleanup
        return original_rmdir(path)

    def run(argv, **kwargs):
        if argv[0] == "sftp" and primary_fails:
            raise primary
        return result("YOKE_ADMIN_STAGE_OWNED\nYOKE_ADMIN_SCRIPT_VERIFIED")

    monkeypatch.setattr(Path, "rmdir", rmdir)
    monkeypatch.setattr(staging.subprocess, "run", run)
    d = diagnostic()
    with pytest.raises((RuntimeError, FileNotFoundError)) as error:
        staging.stage_script(SSH, b"script", ROOT, d, deadline=staging.time.monotonic() + 90)
    assert d["local_cleanup"] == "unverified"
    if primary_fails:
        assert error.value is primary
        assert primary.local_cleanup_cause is cleanup
    else:
        assert str(error.value) == "windows_admin_local_cleanup_failed"
        assert error.value.__cause__ is cleanup


@pytest.mark.windows_only(reason="requires elevated native Windows PowerShell")
def test_native_private_staging_collision_and_hash_cleanup_preserve_unknown_bytes():
    import ctypes

    assert ctypes.windll.shell32.IsUserAnAdmin(), "native staging fixture requires elevation"
    root = r"C:\ProgramData\YokeQaProvision-test-" + uuid4().hex
    payload = b"public staged script"

    def ps(script):
        return subprocess.run(staging.command(script).split(), capture_output=True, text=True, timeout=30)

    prepare = staging.PREPARE.replace("ROOT", staging.quote(root)).replace("CHECK_DIRECTORY", staging.CHECK_DIRECTORY)
    try:
        assert ps(prepare).returncode == 0
        assert ps(prepare).returncode != 0  # collision never replaces the directory
        assert ps(staging.cleanup_script(root, owned=False, payload=payload)).returncode != 0
        write = "$ErrorActionPreference='Stop';[IO.File]::WriteAllBytes(" + staging.quote(root + r"\script.ps1") + ",[Convert]::FromBase64String('" + base64.b64encode(payload).decode() + "'))"
        assert ps(write).returncode == 0
        assert ps(staging.cleanup_script(root, owned=True, payload=b"different")).returncode != 0
        assert Path(root, "script.ps1").read_bytes() == payload
        file = staging.quote(root + r"\script.ps1")
        broaden = "$p=" + file + ";$a=Get-Acl -LiteralPath $p;$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-1-0'),'Read','Allow'));Set-Acl -LiteralPath $p -AclObject $a"
        assert ps(broaden).returncode == 0
        assert ps(staging.cleanup_script(root, owned=True, payload=payload)).returncode != 0
        assert Path(root, "script.ps1").read_bytes() == payload
        restore = "$p=" + file + ";$a=[Security.AccessControl.FileSecurity]::new();$a.SetOwner([Security.Principal.WindowsIdentity]::GetCurrent().User);$a.SetAccessRuleProtection($false,$false);Set-Acl -LiteralPath $p -AclObject $a"
        assert ps(restore).returncode == 0
        assert ps(staging.cleanup_script(root, owned=True, payload=payload)).returncode == 0
        assert not Path(root).exists()
    finally:
        # Test owns exactly this directory/file; do not recurse or discard other bytes.
        ps(staging.cleanup_script(root, owned=True, payload=payload))

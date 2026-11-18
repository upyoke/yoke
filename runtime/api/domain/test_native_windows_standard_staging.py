"""Standard-user SFTP materialization, ambiguity and exact cleanup contracts."""

from contextlib import contextmanager
import hashlib
from types import SimpleNamespace
import subprocess

import pytest

from yoke_harness.native_windows import admin_staging, standard_staging, transport
from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport


def completed(code=0, output=""):
    return subprocess.CompletedProcess([], code, output, "private stderr")


def control():
    c = object.__new__(transport.WindowsTransport)
    c.home = r"C:\Users\controller 雪 with spaces"
    c._key_path, c._host, c._user, c._control_path = "key", "host", "qa", None
    c.os = "windows"
    c.secret_values = ()
    return c


@pytest.mark.parametrize(
    ("os_name", "verified_admin", "negation", "unexpected_owner"),
    [
        ("wsl", True, "!", "-notin @($id.User.Value,'S-1-5-32-544')"),
        ("wsl", False, "", "-ne $id.User.Value"),
        ("windows", True, "", "-ne $id.User.Value"),
        ("windows", False, "", "-ne $id.User.Value"),
    ],
)
def test_sftp_profile_staging_enforces_the_windows_route_identity(
    monkeypatch, os_name, verified_admin, negation, unexpected_owner
):
    c = control()
    c.os = os_name
    c.windows_facts = {"admin": verified_admin}
    policies = []

    def stage(ssh, payload, root, diagnostics, *, deadline, policy):
        policies.append(policy)
        diagnostics["remote_directory_owned"] = True

    monkeypatch.setattr(admin_staging, "stage_script", stage)
    monkeypatch.setattr(SshTestMachineTransport, "_run", lambda *args, **kwargs: completed())
    with standard_staging.verified_payload(c, b"public test payload"):
        pass
    assert len(policies) == 1
    policy = policies[0]
    role_check = f"if({negation}([Security.Principal.WindowsPrincipal]::new($id)).IsInRole("
    assert role_check in policy["prepare"]
    assert role_check in policy["directory"]
    assert unexpected_owner in policy["owner"]
    assert "GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $id.User.Value" in policy["directory"]


@pytest.mark.parametrize("pending", [False, True])
def test_staging_cleans_terminal_work_and_preserves_ambiguous_execution(monkeypatch, pending):
    c, calls = control(), []

    def stage(ssh, payload, root, diagnostic, **kwargs):
        assert ssh[-1] == "qa@host" and "EncodedCommand" not in " ".join(ssh)
        assert all(option in ssh for option in ("ControlMaster=no", "ControlPersist=no", "ControlPath=none"))
        diagnostic["remote_directory_owned"] = True
        diagnostic["last_verified_offset"] = len(payload)

    monkeypatch.setattr(admin_staging, "stage_script", stage)
    monkeypatch.setattr(SshTestMachineTransport, "_run", lambda self, script, **kw: calls.append(script) or completed())
    with standard_staging.verified_payload(c, b"public bytes") as stage:
        stage.execution_pending = pending
    assert stage.diagnostics["cleanup"] == ("preserved_ambiguous_execution" if pending else "verified_absent")
    assert len(calls) == (0 if pending else 1)


def test_failed_staging_never_yields_and_retains_original_and_cleanup(monkeypatch):
    primary = FileNotFoundError("private primary")
    cleanup = OSError("private cleanup")

    def fail(*args, **kwargs):
        raise primary

    def fail_cleanup(*args, **kwargs):
        raise cleanup

    monkeypatch.setattr(admin_staging, "stage_script", fail)
    monkeypatch.setattr(SshTestMachineTransport, "_run", fail_cleanup)
    with pytest.raises(FileNotFoundError) as error:
        with standard_staging.verified_payload(control(), b"bytes"):
            pytest.fail("unverified bytes reached execution")
    assert error.value is primary
    assert primary.staging_cleanup_cause is cleanup
    assert primary.staging_diagnostics["cleanup"] == "unverified"
    assert primary.staging_diagnostics["sha256"] == hashlib.sha256(b"bytes").hexdigest()


@pytest.mark.parametrize("size", [0, 10, 4096])
@pytest.mark.parametrize("exit_code", [0, 124, 255])
def test_all_upload_sizes_commit_verified_sftp_and_preserve_ambiguous_commit(monkeypatch, size, exit_code):
    c, calls = control(), []
    stage = SimpleNamespace(path="'verified-stage'", diagnostics={}, execution_pending=False)

    @contextmanager
    def verified(owner, payload):
        assert owner is c and payload == b"x" * size
        yield stage

    def run(owner, script, **kwargs):
        assert stage.execution_pending
        assert "input_text" not in kwargs
        calls.append(script)
        return completed(exit_code)

    monkeypatch.setattr(transport, "verified_payload", verified)
    monkeypatch.setattr(SshTestMachineTransport, "_run", run)
    if exit_code:
        with pytest.raises(RuntimeError):
            c._upload_bytes(r"C:\Users\qa\literal ' file", b"x" * size)
    else:
        assert c._upload_bytes(r"C:\Users\qa\literal ' file", b"x" * size)
    assert "Move-Item -LiteralPath 'verified-stage'" in calls[0]
    assert stage.execution_pending == (exit_code in (124, 255))


@pytest.mark.parametrize("exit_code", [0, 124, 255])
def test_large_script_keeps_optional_stdin_separate_and_preserves_ambiguity(monkeypatch, exit_code):
    stage = SimpleNamespace(path="'verified-stage'", diagnostics={}, execution_pending=False)
    script, secret = "Write-Output '雪';" * 1000, "optional stdin"

    @contextmanager
    def verified(owner, payload):
        assert payload == script.encode("utf-8-sig") and secret.encode() not in payload
        yield stage

    def run(owner, command, **kwargs):
        assert stage.execution_pending
        assert command == "& 'verified-stage'" and kwargs["input_text"] == secret
        return completed(exit_code)

    monkeypatch.setattr(transport, "verified_payload", verified)
    monkeypatch.setattr(SshTestMachineTransport, "_run", run)
    assert control()._run(script, input_text=secret).returncode == exit_code
    assert stage.execution_pending == (exit_code in (124, 255))


@pytest.mark.parametrize("exit_code", [0, 7])
def test_cleanup_failure_retains_actual_execution_result(monkeypatch, exit_code):
    original = completed(exit_code, "original guest output")
    cleanup = completed(1, "cleanup output")
    replies = iter([original, cleanup])

    def stage(ssh, payload, root, diagnostics, **kwargs):
        diagnostics["remote_directory_owned"] = True
        diagnostics["last_verified_offset"] = len(payload)

    monkeypatch.setattr(admin_staging, "stage_script", stage)
    monkeypatch.setattr(SshTestMachineTransport, "_run", lambda *a, **kw: next(replies))
    with pytest.raises(RuntimeError) as error:
        control()._run("Write-Output 'public';" * 1000)
    assert error.value.primary_result is original
    assert error.value.cleanup_result is cleanup
    assert error.value.staging_diagnostics["cleanup"] == "unverified"


@pytest.mark.parametrize("administrator", [False, True])
def test_staging_commands_fit_final_windows_command_boundary(administrator):
    c = control()
    root = c.home + r"\.yoke-stage-" + "1" * 32
    policy = standard_staging.profile_policy(c.home, administrator=administrator)
    prepare = policy["prepare"].replace("ROOT", transport.quote(root)).replace("CHECK_DIRECTORY", policy["directory"])
    cleanup = admin_staging.cleanup_script(root, owned=True, payload=b"bytes", policy=policy)
    assert "$home=" not in prepare.lower()
    assert len(admin_staging.command(prepare)) < 8000
    assert len(c._ssh_argv(cleanup)[-1]) < 8000


@pytest.mark.parametrize("ambiguous", [False, True])
def test_desktop_upload_failure_keeps_primary_and_records_exact_acquisition(monkeypatch, ambiguous):
    from yoke_harness.native_windows.desktop import desktop_script

    c, calls, uploaded = control(), [], []
    primary = RuntimeError("private upload failure")
    if ambiguous:
        primary.staging_diagnostics = {"cleanup": "preserved_ambiguous_execution"}

    def upload(path, text):
        uploaded.append(path)
        if len(uploaded) == 2:
            raise primary

    c.upload_remote_text = upload
    c._run = lambda script, **kw: calls.append(script) or completed(1)
    with pytest.raises(RuntimeError) as error:
        desktop_script(c, "Write-Output 'public'")
    assert error.value is primary
    assert primary.desktop_diagnostics["files"][0]["path"] == uploaded[0]
    if ambiguous:
        assert not calls
        assert primary.desktop_diagnostics["cleanup"] == "preserved_ambiguous_upload"
    else:
        assert len(calls) == 1 and "Get-FileHash" in calls[0]
        assert "Remove-YokeTask" not in calls[0]
        assert primary.desktop_cleanup_cause
        assert primary.desktop_diagnostics["cleanup"] == "unverified"


def verify_real_standard_sftp(c):
    """Called by the disposable Windows SSH client matrix with a real standard user."""
    from uuid import uuid4

    destination = c.home + "\\sftp-fixture-" + uuid4().hex + ".bin"
    try:
        for payload in (b"", b"small\x00\xff", bytes(range(256)) * 20):
            assert c._upload_bytes(destination, payload)
            assert c.read_remote_bytes(destination, max_bytes=8192) == payload
        large = c._run("# public padding\n" * 500 + "Write-Output 'LARGE_SFTP_EXECUTED'")
        assert large.returncode == 0 and "LARGE_SFTP_EXECUTED" in large.stdout
        assert large.staging_diagnostics["cleanup"] == "verified_absent"
        with standard_staging.verified_payload(c, b"public fixture") as stage:
            root = stage.diagnostics["path"]
            policy = standard_staging.profile_policy(c.home)
            prepare = policy["prepare"].replace("ROOT", transport.quote(root)).replace("CHECK_DIRECTORY", policy["directory"])
            collision = SshTestMachineTransport._run(c, prepare)
            assert collision.returncode != 0
            mismatch = admin_staging.cleanup_script(root, owned=True, payload=b"different", policy=policy)
            assert SshTestMachineTransport._run(c, mismatch).returncode != 0
            assert c.read_remote_bytes(root + r"\script.ps1", max_bytes=8192) == b"public fixture"
            file = transport.quote(root + r"\script.ps1")
            broaden = "$p=" + file + ";$a=Get-Acl -LiteralPath $p;$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-1-0'),'Read','Allow'));Set-Acl -LiteralPath $p -AclObject $a"
            assert c._run(broaden).returncode == 0
            cleanup = admin_staging.cleanup_script(root, owned=True, payload=b"public fixture", policy=policy)
            assert SshTestMachineTransport._run(c, cleanup).returncode != 0
            assert c.read_remote_bytes(root + r"\script.ps1", max_bytes=8192) == b"public fixture"
            restore = "$p=" + file + ";$a=[Security.AccessControl.FileSecurity]::new();$a.SetOwner([Security.Principal.WindowsIdentity]::GetCurrent().User);$a.SetAccessRuleProtection($false,$false);Set-Acl -LiteralPath $p -AclObject $a"
            assert c._run(restore).returncode == 0
        assert stage.diagnostics["cleanup"] == "verified_absent"
        from yoke_harness.native_windows.desktop import desktop_script

        original_upload, owned = c.upload_remote_text, []
        primary = RuntimeError("fixture second upload refused")

        def partial_upload(path, text):
            owned.append(path)
            if len(owned) == 2:
                raise primary
            return original_upload(path, text)

        c.upload_remote_text = partial_upload
        try:
            with pytest.raises(RuntimeError) as error:
                desktop_script(c, "Write-Output 'public fixture'")
            assert error.value is primary
            assert primary.desktop_diagnostics["cleanup"] == "verified_absent"
            for path in owned:
                check = c._run("Test-Path -LiteralPath " + transport.quote(path))
                assert check.returncode == 0 and check.stdout.strip() == "False"
        finally:
            c.upload_remote_text = original_upload
        absent = c._run("@(Get-ChildItem -LiteralPath " + transport.quote(c.home) + " -Filter '.yoke-stage-*' -Force).Count")
        assert absent.returncode == 0 and absent.stdout.strip() == "0"
    finally:
        c._run("Remove-Item -LiteralPath " + transport.quote(destination) + " -Force -ErrorAction SilentlyContinue")

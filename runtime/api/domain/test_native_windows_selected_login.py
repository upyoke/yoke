"""Every Windows SSH and SFTP step logs in as the transport's selected user."""

import base64
import subprocess

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.native_windows import transport


def control(login_user):
    c = object.__new__(transport.WindowsTransport)
    c.home = r"C:\Users\Zoë Tester" if login_user else r"C:\Users\qa"
    c._key_path, c._host, c._user, c._control_path = "key", "lab.example.ts.net", "qa", None
    c.os = "windows"
    c.secret_values = ()
    c.login_user = login_user
    return c


def decoded(argv):
    return base64.b64decode(argv[-1].rsplit(" ", 1)[-1]).decode("utf-16-le")


@pytest.mark.parametrize("login_user", [None, "Zoë Tester"])
def test_staging_execution_and_cleanup_share_the_selected_login(monkeypatch, login_user):
    c, calls = control(login_user), []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "sftp":
            return subprocess.CompletedProcess(argv, 0, "", "")
        script = decoded(argv)
        marker = ("YOKE_ADMIN_STAGE_OWNED" if "Staging collision" in script
                  else "YOKE_ADMIN_SCRIPT_VERIFIED" if "Staged script differs" in script
                  else "ok")
        return subprocess.CompletedProcess(argv, 0, marker + "\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert c._run("Write-Output 'small'").returncode == 0
    assert c._run("Write-Output 'public';" * 1000).returncode == 0
    login = login_user or "qa"
    # ordinary, prepare, sftp, verify, staged execution, cleanup
    assert [argv[0] for argv in calls] == ["ssh", "ssh", "sftp", "ssh", "ssh", "ssh"]
    for argv in calls:
        at = argv.index(f'User="{login}"')
        assert argv[at - 1] == "-o"
        assert "-l" not in argv and not any("@" in value for value in argv)
    sftp = calls[2]
    assert sftp[-1] == "lab.example.ts.net" and sftp[-3:-1] == ["-b", "-"]
    for argv in calls[:2] + calls[3:]:
        assert argv[-2] == "lab.example.ts.net"
    assert "Remove-Item" in decoded(calls[-1])


def test_ssh_reads_the_quoted_login_literally():
    argv = control("Zoë Tester").connection_prefix()
    at = argv.index("-o", argv.index("ControlPath=none"))
    resolved = subprocess.run(
        ["ssh", "-G", "-F", "none", argv[at], argv[at + 1], "qa@" + argv[-1]],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert resolved.returncode == 0, resolved.stderr
    assert "user Zoë Tester" in resolved.stdout.splitlines()


@pytest.mark.parametrize("login_user", ['bad"name', "bad\\name", "bad\nname"])
def test_unquotable_login_refuses_by_name(login_user):
    with pytest.raises(HostControlLocalError) as error:
        control(login_user).connection_prefix()
    assert error.value.code == "native_windows_login_user_invalid"

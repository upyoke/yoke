"""Administrator exec uses stored credentials without exposing them."""

from __future__ import annotations

import shlex
import subprocess
import sys

import pytest

from yoke_cli.commands.adapters import test_machine_exec as adapter
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_harness import test_machine_admin as admin
from yoke_harness.test_machine_remote_exec import RemoteExecRefusal, run_remote_command


PASSWORD = "private-$-pässword"


@pytest.mark.parametrize("os_name", ["linux", "macos"])
def test_admin_cli_reads_only_named_machine_secret_and_passes_it_to_product(
    monkeypatch, tmp_path, os_name
):
    calls = []
    reads = []
    monkeypatch.setattr(adapter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        adapter, "build_actor", lambda **_: type("Actor", (), {"session_id": "mine"})()
    )
    monkeypatch.setattr(adapter.machine_config, "yoke_home", lambda: tmp_path)
    monkeypatch.setattr(
        adapter,
        "call_dispatcher",
        lambda **_: FunctionCallResponse(
            success=True,
            function="test_machine.get",
            version="v1",
            result={
                "machine": "fixture",
                "settings": {
                    "host": "fixture.example",
                    "user": "tester",
                    "os": os_name,
                },
            },
        ),
    )
    monkeypatch.setattr(
        admin,
        "read_machine_capability_secret",
        lambda *args: reads.append(args) or PASSWORD,
    )
    monkeypatch.setattr(
        "yoke_harness.test_machine_remote_exec.run_remote_command",
        lambda **kwargs: (
            calls.append(kwargs) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )
    assert (
        adapter.test_machine_exec(["--project", "demo", "--admin", "--", "id", "-u"])
        == 0
    )
    assert reads == [("demo", "test-machine:fixture", "desktop_password")]
    assert calls[0]["administrator_password"] == PASSWORD


@pytest.mark.parametrize("os_name", ["linux", "macos"])
def test_missing_credential_refuses_before_connecting(monkeypatch, os_name):
    monkeypatch.setattr(admin, "read_machine_capability_secret", lambda *_: None)
    with pytest.raises(RemoteExecRefusal) as raised:
        admin.administrator_password(project="demo", machine="fixture", os_name=os_name)
    assert raised.value.code == "test_machine_admin_credential_missing"
    assert "test-machine:fixture.desktop_password" in str(raised.value)
    assert "--value-file FILE" in raised.value.recovery


@pytest.mark.parametrize(
    "password", ["two\nlines", "nul\0value", "x" * (admin.MAX_PASSWORD_BYTES + 1)]
)
def test_invalid_credential_is_refused_without_value(monkeypatch, password):
    monkeypatch.setattr(admin, "read_machine_capability_secret", lambda *_: password)
    with pytest.raises(RemoteExecRefusal) as raised:
        admin.administrator_password(project="demo", machine="fixture", os_name="linux")
    assert raised.value.code == "test_machine_admin_credential_invalid"
    assert password not in str(raised.value)


def test_unsupported_os_refuses_before_loading_secret(monkeypatch):
    monkeypatch.setattr(
        admin, "read_machine_capability_secret", lambda *_: pytest.fail("must not read")
    )
    with pytest.raises(RemoteExecRefusal, match="macOS or Linux"):
        admin.administrator_password(
            project="demo", machine="fixture", os_name="windows"
        )


def test_sudo_command_preserves_remote_shell_words_and_disconnects_stdin():
    command = admin.administrator_command(
        ["printf", "'%s\\n'", "'a b'", "&&", "id", "-u"]
    )
    words = shlex.split(command[0])
    assert words[:8] == ["sudo", "-k", "-S", "-p", "", "--", "/bin/sh", "-c"]
    assert words[8] == "exec </dev/null; printf '%s\\n' 'a b' && id -u"
    assert PASSWORD not in command[0]


@pytest.mark.parametrize("split", range(1, len(PASSWORD.encode())))
def test_redactor_hides_password_across_every_byte_boundary(split):
    redactor = admin.PasswordRedactor(PASSWORD.encode())
    first = redactor.feed(b"before " + PASSWORD.encode()[:split])
    second = redactor.feed(PASSWORD.encode()[split:] + b" after")
    final = redactor.feed(b"", final=True)
    assert first + second + final == b"before [REDACTED] after"


@pytest.mark.parametrize("returncode", [0, 255])
def test_private_stdin_and_redacted_live_output_and_failure_tails(
    tmp_path, capsys, returncode
):
    calls = []
    program = (
        "import os,sys,time; secret = sys.stdin.buffer.readline().strip(); "
        "os.write(1, b'OUT:' + secret[:5]); "
        "os.write(2, b'ERR:' + secret[:3]); time.sleep(.05); "
        "os.write(1, secret[5:] + b' end'); os.write(2, secret[3:] + b' end'); "
        f"sys.exit({returncode})"
    )

    def popen(argv, **kwargs):
        calls.append(argv)
        assert kwargs["stdin"] == subprocess.PIPE
        return subprocess.Popen([sys.executable, "-c", program], **kwargs)

    kwargs = dict(
        host="fixture.example",
        user="tester",
        command=["id", "-u"],
        yoke_home=tmp_path,
        environ={"SSH_AUTH_SOCK": "/tmp/agent.sock"},
        popen=popen,
        administrator_password=PASSWORD,
    )
    if returncode:
        with pytest.raises(RemoteExecRefusal) as raised:
            run_remote_command(**kwargs)
        assert PASSWORD not in str(raised.value)
        assert "[REDACTED]" in str(raised.value)
    else:
        result = run_remote_command(**kwargs)
        assert result.stdout == "OUT:[REDACTED] end"
        assert result.stderr == "ERR:[REDACTED] end"
        assert PASSWORD not in repr(result)
    captured = capsys.readouterr()
    assert captured.out == "OUT:[REDACTED] end"
    assert captured.err == "ERR:[REDACTED] end"
    assert PASSWORD not in repr(calls)


def test_password_prefix_at_eof_remains_in_failure_tail(tmp_path):
    redactor = admin.PasswordRedactor(PASSWORD.encode())
    assert redactor.feed(b"prefix " + PASSWORD.encode()[:4]) == b"prefix "
    assert redactor.feed(b"", final=True) == PASSWORD.encode()[:4]

"""Host inputs and token delivery cross pipes without logging or empty files."""

import base64
import json
import os
import stat
import subprocess
import sys

import pytest

from yoke_cli.commands import self_host
from yoke_cli.self_host import bundle, first_boot_token, runtime
from yoke_contracts.self_host_bootstrap_output import TOKEN_PREFIX, TOKEN_BODY_LENGTH

TOKEN = TOKEN_PREFIX + "C" * TOKEN_BODY_LENGTH


@pytest.fixture
def target(tmp_path):
    directory = tmp_path / "bundle"
    bundle.write_bundle(directory=str(directory), image="candidate:immutable")
    return directory


@pytest.mark.parametrize("kind", ("mode", "link", "hardlink", "empty", "large"))
def test_unsafe_input_refuses_before_start(tmp_path, kind):
    secret = tmp_path / "secret"
    secret.write_bytes(b"private")
    secret.chmod(0o600)
    if kind == "mode":
        secret.chmod(0o640)
    elif kind == "link":
        source = tmp_path / "source"
        secret.rename(source)
        secret.symlink_to(source)
    elif kind == "hardlink":
        os.link(secret, tmp_path / "other")
    elif kind == "empty":
        secret.write_bytes(b"")
    elif kind == "large":
        secret.write_bytes(b"x" * 10)
    with pytest.raises(
        runtime.SelfHostRuntimeError, match="self_host_handoff_secret_invalid"
    ):
        runtime.read_secret(secret, max_bytes=8)


def test_operator_inputs_are_encoded_in_stdin_not_environment(target, monkeypatch):
    environment = {
        "YOKE_SELF_HOST_HANDOFF": "required",
        "YOKE_PG_DSN_FILE": "/run/secrets/yoke-db-dsn",
    }
    monkeypatch.setattr(
        runtime,
        "compose",
        lambda *_a, **_k: json.dumps(
            {"services": {"core": {"environment": environment}}}
        ).encode(),
    )
    password, header = runtime.bootstrap_inputs(target, "docker")
    assert password == (target / "secrets/db-password").read_bytes()
    payload = json.loads(header)
    assert (
        base64.b64decode(payload["YOKE_PG_DSN_FILE"])
        == (target / "secrets/dsn").read_bytes()
    )
    assert set(payload) == {"YOKE_PG_DSN_FILE"}


def _child(monkeypatch, script):
    original = subprocess.Popen
    calls = []

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return original((sys.executable, "-c", script), **kwargs)

    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    return calls


def test_token_is_durably_saved_before_acknowledgment(target, monkeypatch, capsys):
    path = first_boot_token.token_drop_path(target)
    calls = _child(
        monkeypatch,
        "import sys,json; sys.stdin.buffer.readline(); "
        f"print(json.dumps({{'token':{TOKEN!r}}}),flush=True); "
        "assert sys.stdin.buffer.readline()==b'saved\\n'; "
        f"assert open({str(path)!r}).read().strip()=={TOKEN!r}",
    )
    runtime._receive_token(target, "docker", b"{}\n")
    assert path.read_text().strip() == TOKEN
    assert path.stat().st_uid == os.geteuid()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    command, kwargs = calls[0]
    assert TOKEN not in str(command)
    assert "env" not in kwargs
    assert TOKEN not in capsys.readouterr().out


def test_failed_return_creates_no_empty_token_file(target, monkeypatch):
    _child(monkeypatch, "import sys; sys.stdin.buffer.readline(); sys.exit(1)")
    with pytest.raises(runtime.SelfHostRuntimeError, match="self_host_handoff_failed"):
        runtime._receive_token(target, "docker", b"{}\n")
    assert not first_boot_token.token_drop_path(target).exists()


def test_restart_preserves_an_existing_token(target, monkeypatch):
    path = first_boot_token.token_drop_path(target)
    path.write_text(TOKEN + "\n")
    path.chmod(0o600)
    before = path.read_bytes()
    _child(
        monkeypatch,
        "import sys; sys.stdin.buffer.readline(); print('{\"healthy\":true}',flush=True)",
    )
    runtime._receive_token(target, "docker", b"{}\n")
    assert path.read_bytes() == before


def test_storage_failure_never_acknowledges_success(target, monkeypatch):
    _child(
        monkeypatch,
        "import sys,json; sys.stdin.buffer.readline(); "
        f"print(json.dumps({{'token':{TOKEN!r}}}),flush=True); "
        "assert sys.stdin.buffer.readline()!=b'saved\\n'",
    )

    def refuse(*_a, **_k):
        raise runtime.protection.SelfHostProtectionError("storage unavailable")

    monkeypatch.setattr(runtime.protection, "atomic_replace_bytes", refuse)
    with pytest.raises(runtime.SelfHostRuntimeError, match="self_host_handoff_failed"):
        runtime._receive_token(target, "docker", b"{}\n")
    assert not first_boot_token.token_drop_path(target).exists()


def test_existing_init_command_owns_start_option(target, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(runtime, "start_bundle", lambda **kwargs: calls.append(kwargs))
    assert (
        self_host.self_host_init(
            ["--dir", str(target), "--protect-existing", "--start", "--json"]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["healthy"] is True
    assert calls == [{"directory": str(target)}]


def test_compose_failure_names_operation_without_exposing_output(target, monkeypatch):
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            [], 17, b"private-input", b"private-error"
        ),
    )
    with pytest.raises(
        runtime.SelfHostRuntimeError, match=r"self_host_compose_failed \(up, exit 17\)"
    ) as refusal:
        runtime.compose(target, "docker", ("up", "--wait", "db"))
    assert "private-input" not in str(refusal.value)
    assert "private-error" not in str(refusal.value)
    assert refusal.value.compose_output == b"private-inputprivate-error"


@pytest.mark.parametrize("exit_code", (b"0", b"1"))
def test_import_receipt_requires_successful_container_exit(
    target, monkeypatch, exit_code
):
    monkeypatch.setattr(runtime, "bootstrap_inputs", lambda *_a: (b"password", b"{}\n"))
    monkeypatch.setattr(runtime, "start_database", lambda *_a: None)
    monkeypatch.setattr(runtime, "compose", lambda *_a: b"container")
    _child(
        monkeypatch, "import sys; sys.stdin.buffer.read(); print('receipt',flush=True)"
    )
    calls = []

    def execute(command, **_kwargs):
        calls.append(command[:2])
        return subprocess.CompletedProcess(command, 0, exit_code, b"")

    monkeypatch.setattr(runtime.subprocess, "run", execute)
    if exit_code == b"0":
        assert runtime.import_universe(target, recover=True) == b"receipt\n"
    else:
        with pytest.raises(
            runtime.SelfHostRuntimeError, match="self_host_import_handoff_failed"
        ):
            runtime.import_universe(target, recover=True)
    assert calls == [("docker", "wait"), ("docker", "rm")]

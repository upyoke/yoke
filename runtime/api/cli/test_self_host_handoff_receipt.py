"""The host saves a first-boot token, or names the handoff's failure class."""

import os
import stat
import subprocess
import sys

import pytest

from yoke_cli.commands import self_host
from yoke_cli.self_host import bundle, first_boot_token, handoff_receipt, runtime
from yoke_contracts.self_host_bootstrap_output import TOKEN_PREFIX, TOKEN_BODY_LENGTH

TOKEN = TOKEN_PREFIX + "C" * TOKEN_BODY_LENGTH
POSIX = pytest.mark.posix_only(reason="self-host server runs on Linux or WSL2")
pytestmark = pytest.mark.usefixtures("installed_self_host_prerequisites")


@pytest.fixture
def target(tmp_path):
    directory = tmp_path / "bundle"
    bundle.write_bundle(
        admin_name="Ada Lovelace", directory=str(directory), image="candidate:immutable"
    )
    return directory


@pytest.fixture
def docker(monkeypatch):
    """Answer the core-state reads the failure details make."""
    calls = []

    def execute(command, **_kwargs):
        calls.append(command)
        if command[1:3] == ("compose", "ps"):
            return subprocess.CompletedProcess(command, 0, b"core-id\n", b"")
        if command[1] == "inspect":
            assert command[3] == "{{.State.Status}} exit {{.State.ExitCode}}"
            assert command[4] == "core-id"
            return subprocess.CompletedProcess(command, 0, b"exited exit 3\n", b"")
        raise AssertionError(f"unexpected Docker call {command}")

    monkeypatch.setattr(handoff_receipt.subprocess, "run", execute)
    return calls


def _child(monkeypatch, script):
    original = subprocess.Popen
    calls = []

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return original((sys.executable, "-c", script), **kwargs)

    monkeypatch.setattr(handoff_receipt.subprocess, "Popen", spawn)
    return calls


def _refusal(target):
    with pytest.raises(runtime.SelfHostRuntimeError) as raised:
        handoff_receipt.receive_token(target, "docker", b"{}\n")
    return raised.value


@POSIX
def test_token_is_durably_saved_before_acknowledgment(target, monkeypatch, capsys):
    path = first_boot_token.token_drop_path(target)
    calls = _child(
        monkeypatch,
        "import sys,json; sys.stdin.buffer.readline(); "
        f"print(json.dumps({{'token':{TOKEN!r}}}),flush=True); "
        "assert sys.stdin.buffer.readline()==b'saved\\n'; "
        f"assert open({str(path)!r}).read().strip()=={TOKEN!r}",
    )
    assert handoff_receipt.receive_token(target, "docker", b"{}\n") == {"healthy": True}
    assert path.read_text().strip() == TOKEN
    assert path.stat().st_uid == os.geteuid()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    command, kwargs = calls[0]
    assert TOKEN not in str(command)
    assert "env" not in kwargs
    assert TOKEN not in capsys.readouterr().out


@POSIX
def test_restart_preserves_an_existing_token(target, monkeypatch):
    path = first_boot_token.token_drop_path(target)
    path.write_text(TOKEN + "\n")
    path.chmod(0o600)
    before = path.read_bytes()
    _child(
        monkeypatch,
        "import sys; sys.stdin.buffer.readline(); print('{\"healthy\":true}',flush=True)",
    )
    handoff_receipt.receive_token(target, "docker", b"{}\n")
    assert path.read_bytes() == before


@POSIX
def test_paused_restart_receipt_preserves_token_and_readiness(target, monkeypatch):
    path = first_boot_token.token_drop_path(target)
    path.write_text(TOKEN + "\n")
    path.chmod(0o600)
    _child(
        monkeypatch,
        "import sys; sys.stdin.buffer.readline(); "
        'print(\'{"healthy":false,"paused":true}\',flush=True)',
    )
    assert handoff_receipt.receive_token(target, "docker", b"{}\n") == {
        "healthy": False,
        "paused": True,
    }
    assert path.read_text().strip() == TOKEN


@POSIX
@pytest.mark.parametrize(
    "script,reason",
    (
        ("sys.exit(1)", "self_host_handoff_exec_failed"),
        ("sys.exit(0)", "self_host_handoff_receipt_invalid"),
        ("print('not json',flush=True)", "self_host_handoff_receipt_invalid"),
        (
            'print(\'{"healthy":"maybe"}\',flush=True)',
            "self_host_handoff_receipt_invalid",
        ),
        (
            'print(\'{"error":"bootstrap_closed"}\',flush=True); sys.exit(1)',
            "self_host_handoff_bootstrap_closed",
        ),
        (
            'print(\'{"error":"connect_timeout"}\',flush=True); sys.exit(1)',
            "self_host_handoff_connect_timeout",
        ),
        (
            'print(\'{"error":"unhealthy_timeout"}\',flush=True); sys.exit(1)',
            "self_host_handoff_unhealthy_timeout",
        ),
        (
            'print(\'{"error":"novel"}\',flush=True); sys.exit(1)',
            "self_host_handoff_receipt_invalid",
        ),
    ),
)
def test_each_failure_class_names_its_reason_with_details(
    target, monkeypatch, docker, script, reason
):
    _child(
        monkeypatch,
        "import sys; sys.stdin.buffer.readline(); "
        f"print('client refused {TOKEN}',file=sys.stderr,flush=True); {script}",
    )
    refusal = _refusal(target)
    message = str(refusal)
    assert message.startswith(f"{reason}: ")
    assert handoff_receipt.RECOVERIES[reason] in message
    details = "\n".join(refusal.detail_lines)
    assert "docker compose exec exit: " in details
    assert "Exec stderr: client refused [Yoke API token redacted]" in details
    assert "Core container State.Status / ExitCode: exited exit 3" in details
    assert TOKEN not in details + message
    assert not first_boot_token.token_drop_path(target).exists()


@POSIX
def test_invalid_receipt_keeps_stderr_after_child_exit(target, monkeypatch, docker):
    _child(
        monkeypatch,
        "import sys; sys.stdin.buffer.readline(); "
        f"print('client refused {TOKEN}',file=sys.stderr,flush=True); "
        'print(\'{"healthy":"maybe"}\',flush=True)',
    )
    exchange = handoff_receipt._exchange

    def exchange_and_reap(process, directory, header):
        try:
            return exchange(process, directory, header)
        except handoff_receipt._Refused:
            process.wait(timeout=10)
            raise

    monkeypatch.setattr(handoff_receipt, "_exchange", exchange_and_reap)
    details = "\n".join(_refusal(target).detail_lines)
    assert "docker compose exec exit: 0" in details
    assert "Exec stderr: client refused [Yoke API token redacted]" in details
    assert TOKEN not in details


@POSIX
def test_failure_reasons_are_distinct_and_each_names_a_recovery():
    reasons = handoff_receipt.RECOVERIES
    assert len(set(reasons.values())) == len(reasons)
    assert "self_host_handoff_failed" not in reasons


@POSIX
def test_missing_ack_after_token_names_ack_missing_without_echoing_token(
    target, monkeypatch, docker
):
    _child(
        monkeypatch,
        "import sys,json; sys.stdin.buffer.readline(); "
        f"print(json.dumps({{'token':{TOKEN!r}}}),flush=True); "
        "sys.stdin.buffer.readline(); "
        'print(\'{"error":"ack_missing"}\',flush=True); sys.exit(1)',
    )
    refusal = _refusal(target)
    assert str(refusal).startswith("self_host_handoff_ack_missing: ")
    assert TOKEN not in "\n".join(refusal.detail_lines)


@POSIX
def test_storage_failure_never_acknowledges_success(target, monkeypatch, docker):
    _child(
        monkeypatch,
        "import sys,json; sys.stdin.buffer.readline(); "
        f"print(json.dumps({{'token':{TOKEN!r}}}),flush=True); "
        "assert sys.stdin.buffer.readline()!=b'saved\\n'",
    )

    def refuse(*_a, **_k):
        raise handoff_receipt.protection.SelfHostProtectionError("storage unavailable")

    monkeypatch.setattr(handoff_receipt.protection, "atomic_replace_bytes", refuse)
    refusal = _refusal(target)
    assert str(refusal).startswith("self_host_handoff_token_store_failed: ")
    assert not first_boot_token.token_drop_path(target).exists()


@POSIX
def test_receipt_timeout_names_timeout_and_reads_core_state(
    target, monkeypatch, docker
):
    monkeypatch.setattr(handoff_receipt, "RECEIPT_TIMEOUT_SECONDS", 0.2)
    _child(monkeypatch, "import sys,time; sys.stdin.buffer.readline(); time.sleep(30)")
    refusal = _refusal(target)
    assert str(refusal).startswith("self_host_handoff_timeout: ")
    assert "docker compose exec exit: -9" in refusal.detail_lines[0]
    assert [command[1] for command in docker] == ["compose", "inspect"]


@POSIX
def test_unstartable_exec_names_exec_failed(target, monkeypatch, docker):
    def missing(*_a, **_k):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(handoff_receipt.subprocess, "Popen", missing)
    refusal = _refusal(target)
    assert str(refusal).startswith("self_host_handoff_exec_failed: ")
    assert refusal.detail_lines[0] == "docker compose exec exit: unavailable"


@POSIX
def test_init_start_prints_failure_details_on_stderr(target, monkeypatch, capsys):
    def refuse(**_k):
        raise runtime.SelfHostRuntimeError(
            "self_host_handoff_bootstrap_closed: named", ("Core container: exited",)
        )

    monkeypatch.setattr(runtime, "start_bundle", refuse)
    argv = ["--dir", str(target), "--protect-existing", "--start", "--json"]
    assert self_host.self_host_init(argv) == 1
    err = capsys.readouterr().err
    assert "error: self_host_handoff_bootstrap_closed: named" in err
    assert "  Core container: exited" in err

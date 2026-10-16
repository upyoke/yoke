"""Fallback evaluation remains intact while resident warnings are bounded."""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from yoke_contracts import platform_file_lock

from yoke_cli.commands.adapters import hooks
from yoke_cli import hook_resident_client as client
from yoke_cli.hook_resident_client import ResidentUnavailable
from yoke_cli import hook_resident_health as health


def test_warning_claim_survives_separate_hook_processes(tmp_path):
    script = (
        "from pathlib import Path; "
        "from yoke_cli.hook_resident_health import claim_fallback_warning; "
        "import sys; print(claim_fallback_warning(Path(sys.argv[1])))"
    )
    answers = [
        subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        for _ in range(3)
    ]
    assert answers == ["True", "False", "False"]
    if os.name != "nt":
        assert (tmp_path / "fallback-warning").stat().st_mode & 0o777 == 0o600


def test_concurrent_hook_process_handles_claim_only_one_warning(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(
            pool.map(lambda _: health.claim_fallback_warning(tmp_path), range(16))
        )
    assert sum(answers) == 1


def test_warning_interval_and_clock_reversal(monkeypatch, tmp_path):
    now = 1000.0
    monkeypatch.setattr(health.time, "time", lambda: now)
    assert health.claim_fallback_warning(tmp_path)
    now += health.WARNING_INTERVAL_SECONDS - 1
    assert not health.claim_fallback_warning(tmp_path)
    now += 1
    assert health.claim_fallback_warning(tmp_path)
    now -= 100
    assert health.claim_fallback_warning(tmp_path)


def test_warning_state_failure_stays_quiet_and_does_not_follow_symlinks(tmp_path):
    assert not health.claim_fallback_warning(tmp_path / "missing")
    target = tmp_path / "private"
    target.write_text("unchanged", encoding="utf-8")
    (tmp_path / "fallback-warning").symlink_to(target)
    assert not health.claim_fallback_warning(tmp_path)
    assert target.read_text(encoding="utf-8") == "unchanged"


@pytest.mark.parametrize("event", ["PreToolUse", "PostToolUse", "Stop"])
def test_repeated_hooks_warn_once_and_preserve_fallback_verdict(
    monkeypatch,
    tmp_path,
    capsys,
    event,
):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("YOKE_HOOK_CONFIG_OWNER", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(health.time, "time", lambda: 1000.0)
    calls = []

    def unavailable(*args, **kwargs):
        raise ResidentUnavailable(
            "YOKE_HOOK_RESIDENT_UNREACHABLE",
            "test resident down",
            log_path=tmp_path / "evaluator.log",
        )

    def fallback(*args, **kwargs):
        calls.append((args, kwargs))
        return 7

    monkeypatch.setattr(
        "yoke_cli.hook_resident_client.evaluate_with_resident", unavailable
    )
    monkeypatch.setattr(hooks, "_evaluate_inprocess", fallback)
    for _ in range(3):
        assert hooks.hook_evaluate([event]) == 7
    stderr = capsys.readouterr().err
    assert stderr.count("WARNING: YOKE_HOOK_RESIDENT_UNREACHABLE") == 1
    assert "yoke watch doctor -- --only hook-resident" in stderr
    assert len(calls) == 3
    assert all(args[0] == event for args, _ in calls)
    assert all(
        kw["fallback_reason"] == "YOKE_HOOK_RESIDENT_UNREACHABLE" for _, kw in calls
    )


def test_warning_lock_contention_does_not_block(tmp_path):
    with (tmp_path / "fallback-warning").open("w", encoding="utf-8") as state:
        platform_file_lock.acquire_exclusive_nonblocking(state.fileno())
        try:
            assert not health.claim_fallback_warning(tmp_path)
        finally:
            platform_file_lock.release_exclusive(state.fileno())


def test_warning_state_failure_preserves_hook_fallback(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    def unavailable(*args, **kwargs):
        raise ResidentUnavailable(
            "YOKE_HOOK_RESIDENT_UNREACHABLE",
            "test resident down",
            log_path=tmp_path / "missing" / "evaluator.log",
        )

    monkeypatch.setattr(
        "yoke_cli.hook_resident_client.evaluate_with_resident", unavailable
    )
    monkeypatch.setattr(hooks, "_evaluate_inprocess", lambda *a, **kw: 7)
    assert hooks.hook_evaluate(["PreToolUse"]) == 7
    assert "WARNING:" not in capsys.readouterr().err


def test_missing_unix_socket_transport_uses_named_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.delattr(client.socket, "AF_UNIX", raising=False)

    with pytest.raises(ResidentUnavailable) as failure:
        client.evaluate_with_resident("SessionStart", "{}")

    assert failure.value.code == "YOKE_HOOK_RESIDENT_UNSUPPORTED"
    assert failure.value.log_path == tmp_path / "hook-evaluator" / "evaluator.log"


def test_missing_unix_socket_transport_has_a_health_verdict(monkeypatch, tmp_path):
    monkeypatch.delattr(health.socket, "AF_UNIX", raising=False)
    assert health.resident_revision_problem(tmp_path / "socket", "expected").startswith(
        "YOKE_HOOK_RESIDENT_UNSUPPORTED:"
    )


def test_missing_unix_socket_transport_reaches_canonical_fallback(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.delattr(client.socket, "AF_UNIX", raising=False)
    calls = []
    monkeypatch.setattr(
        hooks,
        "_evaluate_inprocess",
        lambda *args, **kwargs: calls.append((args, kwargs)) or 0,
    )

    assert hooks.hook_evaluate(["SessionStart"]) == 0
    assert calls[0][1]["fallback_reason"] == "YOKE_HOOK_RESIDENT_UNSUPPORTED"


@pytest.mark.parametrize(
    "loaded,expected,version,installed,reason",
    [
        ("a" * 40, "a" * 40, "", "", ""),
        ("b" * 40, "a" * 40, "", "", "YOKE_HOOK_VERSION_MISMATCH"),
        ("unknown", "unknown", "0.1.1+launch.400", "0.1.1+launch.400", ""),
        (
            "unknown",
            "unknown",
            "0.1.1+launch.399",
            "0.1.1+launch.400",
            "YOKE_HOOK_VERSION_MISMATCH",
        ),
        ("unknown", "unknown", "", "", "YOKE_HOOK_REVISION_UNKNOWN"),
    ],
)
@pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="resident health requires Unix sockets"
)
def test_health_reads_identity_without_evaluating_or_restarting(
    monkeypatch, loaded, expected, version, installed, reason
):
    import tempfile
    import threading
    from pathlib import Path
    from yoke_contracts.hook_evaluator_protocol import receive_frame
    from yoke_harness import hook_resident_probe

    monkeypatch.setattr(
        "yoke_contracts.engine_version.installed_engine_version", lambda: installed
    )
    monkeypatch.setattr(hook_resident_probe, "_LOADED_VERSION", version)
    frames = []
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="hh-") as directory:
        address = Path(directory) / "socket"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(address))
            listener.listen()

            def answer():
                peer, _ = listener.accept()
                with peer:
                    frame = receive_frame(peer)
                    frames.append(frame)
                    assert hook_resident_probe.answer_probe(peer, frame, loaded)

            worker = threading.Thread(target=answer)
            worker.start()
            result = health.resident_revision_problem(address, expected)
            worker.join(timeout=2)
            assert not worker.is_alive()
    assert frames == [{"kind": "health"}]
    assert reason in result if reason else result == ""

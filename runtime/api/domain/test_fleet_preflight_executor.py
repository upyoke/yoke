"""A declared ``release.preflight_executor`` replaces the local fleet kernel.

Both callers -- operator ``yoke watch preflight`` and the release-triggered
rehearsal -- run the declared executor with the same arguments, watcher
output and exit code; unset, they run the local kernel exactly as before.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from yoke_core.domain import deploy_pipeline_fleet_rehearsal as rehearsal
from yoke_core.domain import (
    deployment_start_timing,
    fleet_preflight_executor,
    migration_preflight_receipt_store,
    watch_capture_binding,
    watch_runner,
)
from yoke_core.domain.environment_declared_facts import PREFLIGHT_EXECUTOR_PATH
from yoke_core.tools import watch_preflight

SHA = "c" * 40
# Exactly the arguments the release rehearsal builds for a release commit.
ARGS = [
    "--project",
    "acme",
    "--model",
    "primary",
    "prod",
    "--record-receipt",
    "--product-sha",
    SHA,
    "--receipt-env",
    "control",
]
KERNEL = [sys.executable, "-m", "yoke_core.tools.preflight_fleet_migrations"]


def _declare(monkeypatch: pytest.MonkeyPatch, value: object, error: str = "") -> list:
    reads: list = []

    def read_coverage(*, project: str, environment: str, paths):
        reads.append((project, environment, list(paths)))
        if error:
            return {}, error
        return ({PREFLIGHT_EXECUTOR_PATH: value} if value is not None else {}), ""

    monkeypatch.setattr(
        migration_preflight_receipt_store, "read_coverage", read_coverage
    )
    return reads


def _fake_executor(tmp_path: Path, rc: int) -> tuple[str, Path]:
    seen = tmp_path / "seen.json"
    script = tmp_path / "remote_preflight.py"
    script.write_text(
        "import json, sys\n"
        f"open({str(seen)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        "print('PASS acme_alpha: 0007_x -> converged')\n"
        "print('FAIL acme_beta: could not copy: pg_dump failed')\n"
        "print('1 passed, 1 failed')\n"
        f"raise SystemExit({rc})\n",
        encoding="utf-8",
    )
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}", seen


def _operator_run(tmp_path: Path, args: list[str]) -> int:
    return watch_preflight.main(
        [
            "--raw-capture",
            str(tmp_path / "raw.log"),
            "--progress-capture",
            str(tmp_path / "progress.log"),
            "--",
            *args,
        ]
    )


def _release_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, run_id: str = ""
) -> tuple[int, str]:
    """Drive the release gate's rehearsal of an engine-tenants fleet."""
    raw, progress = tmp_path / "raw.log", tmp_path / "progress.log"
    monkeypatch.setattr(
        watch_capture_binding, "mint_cli_capture_paths", lambda _kind: (raw, progress)
    )
    monkeypatch.setattr(watch_capture_binding, "stamp_writer", lambda *_a: None)
    monkeypatch.setattr(deployment_start_timing, "current_run_id", lambda: run_id)
    return rehearsal._rehearse_release_source(
        "acme",
        "primary",
        {"kind": "engine_tenants"},
        environment="prod",
        repository="/repo",
        release_sha=SHA,
        modules_dir="migrations",
        history=("0001_first",),
        schema_digest="d" * 64,
        receipt_environment="control",
    )


def _local_engine_matches(monkeypatch: pytest.MonkeyPatch) -> list:
    checks: list = []
    monkeypatch.setattr(
        rehearsal.release_source,
        "engine_source_mismatch",
        lambda *a: checks.append(a) or "",
    )
    return checks


@pytest.mark.parametrize("caller", ["operator", "release"])
def test_declared_executor_runs_with_same_args_output_and_exit(
    caller: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("DEPLOYMENT_RUN_ID", raising=False)
    executor, seen = _fake_executor(tmp_path, rc=3)
    reads = _declare(monkeypatch, executor)
    engine_checks = _local_engine_matches(monkeypatch)

    if caller == "operator":
        rc = _operator_run(tmp_path, ARGS)
        expected = ARGS
    else:
        rc, refusal = _release_run(tmp_path, monkeypatch, run_id="run-9")
        assert refusal == ""
        expected = ["--run-id", "run-9", *ARGS]

    assert rc == 3
    assert reads == [("acme", "prod", [PREFLIGHT_EXECUTOR_PATH])]
    assert json.loads(seen.read_text()) == expected
    # The executor rehearses --product-sha itself; this machine's engine is moot.
    assert engine_checks == []
    out = capsys.readouterr().out
    assert "FAIL acme_beta: could not copy" in out
    assert "1 passed, 1 failed" in out
    assert "fleet_preflight_executor_failed" in out
    assert "exited with code 3" in out
    assert "# watch_preflight exit=3" in out
    assert "# watch_preflight exit=3" in (tmp_path / "progress.log").read_text()


@pytest.mark.parametrize("caller", ["operator", "release"])
@pytest.mark.parametrize("declared", [None, "", "   "])
def test_unset_executor_runs_the_local_kernel_unchanged(
    caller: str,
    declared: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEPLOYMENT_RUN_ID", raising=False)
    _declare(monkeypatch, declared)
    watched: list[list[str]] = []

    def run_watcher(*, argv, exit_metadata, **_kwargs):
        watched.append(list(argv))
        assert "fleet_preflight_failed" in exit_metadata(1)
        return 5

    monkeypatch.setattr(watch_runner, "run_watcher", run_watcher)
    engine_checks = _local_engine_matches(monkeypatch)
    if caller == "operator":
        rc = _operator_run(tmp_path, ARGS)
    else:
        rc, refusal = _release_run(tmp_path, monkeypatch)
        assert refusal == ""

    assert rc == 5
    assert watched == [[*KERNEL, *ARGS]]
    assert len(engine_checks) == (1 if caller == "release" else 0)


def test_incomplete_arguments_reach_the_kernel_without_a_settings_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = _declare(monkeypatch, "never-read")
    assert fleet_preflight_executor.resolve(["--help"]).argv(["--help"]) == [
        *KERNEL,
        "--help",
    ]
    assert fleet_preflight_executor.resolve(["prod"]).argv(["prod"]) == [
        *KERNEL,
        "prod",
    ]
    assert reads == []


def test_missing_executor_refuses_with_its_reason_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _declare(monkeypatch, str(tmp_path / "no-such-executor"))

    rc = _operator_run(tmp_path, ARGS)

    assert rc == watch_runner.WRAPPER_LAUNCH_ERROR
    out = capsys.readouterr().out
    assert "fleet_preflight_executor_failed" in out
    assert "could not start" in out
    assert "--set release.preflight_executor=<command>" in out


def test_unreadable_declaration_refuses_instead_of_copying_locally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _declare(monkeypatch, None, error="control plane unreachable")

    rc = _operator_run(tmp_path, ARGS)

    assert rc == 2
    out = capsys.readouterr().out
    assert "fleet_preflight_executor_unreadable" in out
    assert "control plane unreachable" in out
    assert "fleet_preflight_executor_unreadable" in (tmp_path / "raw.log").read_text()


def test_unparseable_executor_refuses_before_running_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _declare(monkeypatch, "'unterminated")

    command = fleet_preflight_executor.resolve(ARGS)

    assert "fleet_preflight_executor_invalid" in command.refusal
    assert "No closing quotation" in command.refusal
    assert command.argv(ARGS)[:2] == [sys.executable, "-c"]


@pytest.mark.parametrize(
    "local_path", [["--checkout", "/home/me/acme"], ["--engine-wheel", "/tmp/e.whl"]]
)
def test_caller_local_paths_refuse_an_executor_run(
    local_path: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _declare(monkeypatch, "remote-preflight --host db")

    command = fleet_preflight_executor.resolve([*local_path, *ARGS])

    assert "fleet_preflight_executor_local_path" in command.refusal
    assert local_path[0] in command.refusal
    assert "--product-sha" in command.refusal
    assert command.executor == ""


def test_release_rehearsal_reports_an_unreadable_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _declare(monkeypatch, None, error="control plane unreachable")
    engine_checks = _local_engine_matches(monkeypatch)

    rc, refusal = _release_run(tmp_path, monkeypatch)

    assert rc == 1
    assert refusal.startswith("release fleet rehearsal refused: ")
    assert "fleet_preflight_executor_unreadable" in refusal
    assert engine_checks == []

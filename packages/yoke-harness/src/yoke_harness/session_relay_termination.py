"""Machine-local process reaping for a relay termination job."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import time
from typing import Any, Callable, Mapping

from yoke_cli.config import machine_config
from yoke_contracts.process_ancestry import process_start_time
from yoke_contracts.session_identity import ANCHORS_DIR_NAME
from yoke_harness.session_launch_containment import SUPERVISION_DIRECTORY_NAME


ADAPTER_REVISION = "session-termination-v1"
NATIVE_HANDLE_DIRECTORY_NAME = "session-native-handles"
MAX_RECORD_BYTES = 4096
_TERMINATE_WAIT_SECONDS = 2.0


def local_state_root(state_dir: Path | None) -> Path:
    return state_dir or machine_config.cache_dir()


def _handle_directory(state_dir: Path | None) -> Path:
    directory = local_state_root(state_dir) / NATIVE_HANDLE_DIRECTORY_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    return directory


def _supervision_path(launch_id: str, state_dir: Path | None) -> Path:
    directory = local_state_root(state_dir) / SUPERVISION_DIRECTORY_NAME
    return directory / f"{launch_id}.json"


def _handle_path(launch_id: str, state_dir: Path | None) -> Path:
    return _handle_directory(state_dir) / f"{launch_id}.json"


def read_local_record(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def adopt_launched_session(
    launch_id: str,
    target_session_id: str | None,
    *,
    state_dir: Path | None = None,
) -> bool:
    """Retain a safe PID handle before registration releases containment."""
    source = _supervision_path(launch_id, state_dir)
    record = read_local_record(source)
    if record is None or str(record.get("launch_id") or "") != launch_id:
        return False
    pid = record.get("pid")
    start = record.get("process_start_time")
    if not isinstance(pid, int) or pid <= 0 or not isinstance(start, str) or not start:
        return False
    payload = {
        "launch_id": launch_id,
        "target_session_id": target_session_id or None,
        "native_session_id": record.get("native_session_id"),
        "pid": pid,
        "process_start_time": start,
    }
    try:
        destination = _handle_path(launch_id, state_dir)
        temporary = destination.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    except OSError:
        return False
    return True


def _terminate_pid(pid: int, expected_start: object) -> str:
    if process_start_time(pid) != expected_start:
        return "already_exited"
    try:
        group = os.getpgid(pid)
    except OSError:
        return "already_exited"
    if process_start_time(pid) != expected_start:
        return "already_exited"
    if group == os.getpgrp():
        return "shared_process_group"
    try:
        os.killpg(group, signal.SIGTERM)
    except OSError:
        return "already_exited"
    deadline = time.monotonic() + _TERMINATE_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(group, 0)
        except OSError:
            return "terminated"
        time.sleep(0.1)
    try:
        os.killpg(group, signal.SIGKILL)
    except OSError:
        return "terminated"
    return "killed"


def _terminate_record(path: Path, record: Mapping[str, Any]) -> tuple[int, str] | None:
    pid = record.get("pid") or record.get("anchor_pid")
    start = record.get("process_start_time") or record.get("anchor_start_time")
    if not isinstance(pid, int) or pid <= 0 or not start:
        return None
    result = _terminate_pid(pid, start)
    if result != "shared_process_group":
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return pid, result


def _stop_claude_background_agent(
    native_session_id: str,
    *,
    process_runner: Callable[[tuple[str, ...]], Any] | None = None,
) -> tuple[str, dict[str, object]]:
    from yoke_harness.session_relay_claude_identity import resolve_background_agent
    from yoke_harness.session_relay_claude_native import (
        CLAUDE_AGENT_LIST_ARGUMENTS,
        CLAUDE_BACKGROUND_STOP_COMMAND,
        CLAUDE_NATIVE_COMMAND_TIMEOUT_SECONDS,
        discover_claude_cli,
    )
    from yoke_harness.session_relay_claude_process import run_bounded_claude_process

    executable = discover_claude_cli()
    if executable is None:
        return "not_found", {"background_agent_result": "executable_not_found"}

    def run(arguments: tuple[str, ...]) -> Any:
        if process_runner is not None:
            return process_runner(arguments)
        return run_bounded_claude_process(
            arguments,
            cwd=Path.cwd(),
            environment=os.environ,
            timeout_seconds=CLAUDE_NATIVE_COMMAND_TIMEOUT_SECONDS,
        )

    resolution = resolve_background_agent(
        native_session_id,
        lambda: run((executable, *CLAUDE_AGENT_LIST_ARGUMENTS)),
    )
    evidence: dict[str, object] = {
        "background_agent_result": resolution.result_code,
        "background_agent_lookup_attempts": resolution.attempts,
    }
    if resolution.short_id is None:
        code = (
            "not_found"
            if resolution.result_code
            in {"background_agent_not_found", "native_session_invalid"}
            else "outcome_unknown"
        )
        return code, evidence
    try:
        stopped = run((executable, CLAUDE_BACKGROUND_STOP_COMMAND, resolution.short_id))
    except Exception:
        evidence["background_agent_stop"] = "native_exception"
        return "outcome_unknown", evidence
    evidence["background_agent_stop"] = (
        "completed" if stopped.returncode == 0 else "native_exit"
    )
    evidence["background_agent_stop_duration_ms"] = max(0, int(stopped.duration_ms))
    return ("terminated" if stopped.returncode == 0 else "failed"), evidence


def _matching_resume_records(
    target_session_id: str,
    native_thread_id: str | None,
    state_dir: Path | None,
) -> list[tuple[Path, dict[str, Any]]]:
    directory = local_state_root(state_dir) / SUPERVISION_DIRECTORY_NAME
    matches: list[tuple[Path, dict[str, Any]]] = []
    try:
        candidates = sorted(directory.glob("*.json"))
    except OSError:
        return matches
    identities = {target_session_id}
    if native_thread_id:
        identities.add(str(native_thread_id))
    for path in candidates:
        record = read_local_record(path)
        if record is None or record.get("supervision_kind") != "resume":
            continue
        if str(record.get("native_session_id") or "") in identities:
            matches.append((path, record))
    return matches


def _matching_anchor_records(
    target_session_id: str,
    anchors_dir: Path | None,
) -> list[tuple[Path, dict[str, Any]]]:
    directory = anchors_dir or (machine_config.yoke_home() / ANCHORS_DIR_NAME)
    matches: list[tuple[Path, dict[str, Any]]] = []
    try:
        candidates = sorted(directory.glob("*.json"))
    except OSError:
        return matches
    for path in candidates:
        record = read_local_record(path)
        if record is None or record.get("shared_by_multiple_sessions"):
            continue
        if str(record.get("session_id") or "") == target_session_id:
            matches.append((path, record))
    return matches


def reap_terminated_session(
    job: Mapping[str, Any],
    *,
    state_dir: Path | None = None,
    anchors_dir: Path | None = None,
    claude_process_runner: Callable[[tuple[str, ...]], Any] | None = None,
) -> "Any":
    """Reap launch custody, detached resume, or local process-anchor handles."""
    from yoke_harness.session_relay_runtime import RelayAdapterResult

    target = str(job.get("target_session_id") or job.get("job_id") or "")
    launch_id = str(job.get("target_launch_id") or "")
    native_id = str(job.get("target_native_thread_id") or "") or None
    outcomes: list[str] = []
    evidence: dict[str, object] = {}
    from yoke_harness.session_relay_claude import CLAUDE_CLI_SURFACE

    if str(job.get("surface") or "") == CLAUDE_CLI_SURFACE and native_id:
        background_result, background_evidence = _stop_claude_background_agent(
            native_id,
            process_runner=claude_process_runner,
        )
        outcomes.append(background_result)
        evidence.update(background_evidence)
    records: list[tuple[Path, dict[str, Any]]] = []
    if launch_id:
        handle = _handle_path(launch_id, state_dir)
        record = read_local_record(handle)
        if (
            record is not None
            and str(record.get("launch_id") or "") == launch_id
            and str(record.get("target_session_id") or "") == target
        ):
            records.append((handle, record))
    records.extend(_matching_resume_records(target, native_id, state_dir))
    records.extend(_matching_anchor_records(target, anchors_dir))
    pids: set[int] = set()
    for path, record in records:
        result = _terminate_record(path, record)
        if result is None or result[0] in pids:
            continue
        pids.add(result[0])
        outcomes.append(result[1])
    if "killed" in outcomes:
        code = "killed"
    elif "terminated" in outcomes:
        code = "terminated"
    elif "failed" in outcomes:
        code = "failed"
    elif "outcome_unknown" in outcomes:
        code = "outcome_unknown"
    elif "shared_process_group" in outcomes:
        code = "shared_process_group"
    elif "already_exited" in outcomes:
        code = "already_exited"
    else:
        code = "not_found"
    evidence.update({"result_code": code, "handles_considered": len(records)})
    return RelayAdapterResult(
        code,
        adapter_revision=ADAPTER_REVISION,
        evidence=evidence,
    )


__all__ = [
    "ADAPTER_REVISION",
    "MAX_RECORD_BYTES",
    "NATIVE_HANDLE_DIRECTORY_NAME",
    "adopt_launched_session",
    "local_state_root",
    "read_local_record",
    "reap_terminated_session",
]

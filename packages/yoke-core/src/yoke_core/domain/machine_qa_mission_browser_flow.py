"""Use an awaiting mission's lease for the browser approval its host emitted."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any

from yoke_contracts.qa_mission_scratch import mission_scratch_path
from yoke_core.domain.machine_qa_browser_flow_policy import load_browser_flow
from yoke_core.domain.machine_qa_local_execution import _execution, _mission_contract
from yoke_core.domain.machine_qa_operator_gate import (
    run_machine_browser_approval_with_io,
)
from yoke_core.domain.machine_qa_saved_profile_approval import (
    approve_machine_from_profile,
)


_TRANSCRIPT_PROGRAM = r"""
import json, os, stat, sys
from pathlib import Path
root, path = map(Path, sys.argv[1:])
def refuse(reason):
    print(json.dumps({"ok": False, "reason": reason}))
    raise SystemExit(64)
try:
    for parent in (root, *path.parents):
        if parent == root.parent:
            break
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            refuse("mission_browser_transcript_parent_unsafe")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            refuse("mission_browser_transcript_unsafe")
        with os.fdopen(descriptor, "rb") as stream:
            content = stream.read(128 * 1024 + 1)
        if len(content) > 128 * 1024:
            refuse("mission_browser_transcript_too_large")
        text = content.decode("utf-8")
    except BaseException:
        try: os.close(descriptor)
        except OSError: pass
        raise
except (OSError, UnicodeError):
    refuse("mission_browser_transcript_unavailable")
print(json.dumps({"ok": True, "transcript": text}))
"""


def _transcript_reader(control: Any, scratch: str, path: str):
    selected = PurePosixPath(path)
    root = PurePosixPath(scratch)
    if (
        not selected.is_absolute()
        or ".." in selected.parts
        or root not in selected.parents
    ):
        raise ValueError(
            "mission_browser_transcript_outside_scratch: capture the live installer output inside this mission's scratch directory, then retry"
        )

    def read() -> str:
        completed = control.run_command(
            ["python3", "-c", _TRANSCRIPT_PROGRAM, scratch, path], timeout=30
        )
        try:
            response = json.loads(completed.stdout)
        except (ValueError, TypeError):
            response = {}
        if (
            completed.returncode
            or not isinstance(response, dict)
            or response.get("ok") is not True
        ):
            reason = (
                response.get("reason", "mission_browser_transcript_unavailable")
                if isinstance(response, dict)
                else "mission_browser_transcript_unavailable"
            )
            raise ValueError(
                f"{reason}: capture the live installer output in an owner-only file under {scratch}, then retry; do not paste a link or copy another run's transcript"
            )
        return str(response["transcript"])

    return read


def execute_agent_mission_browser_flow(
    raw_contract: dict[str, Any],
    *,
    execution_id: str,
    transcript_path: str,
    completion_text: list[str],
    timeout_seconds: int,
) -> dict[str, Any]:
    """Reuse the typed recipe gate, retaining its origin and completion checks."""
    contract = _mission_contract(raw_contract)
    execution = _execution(contract)
    flow = load_browser_flow(contract.project_id, "machine_browser_approval")
    read = _transcript_reader(
        execution.control, mission_scratch_path(execution_id), transcript_path
    )
    result = run_machine_browser_approval_with_io(
        read_transcript=read,
        send_keys=lambda keys: not keys,
        action={
            "keys": [],
            "completion_text": completion_text,
            "gate_timeout_seconds": timeout_seconds,
        },
        progress_callback=None,
        allowed_base_urls=execution.allowed_operator_urls,
        flow=flow,
        approve_browser=lambda url, code: approve_machine_from_profile(
            execution.control,
            verification_url=url,
            user_code=code,
            flow=flow,
            timeout_seconds=timeout_seconds,
        ),
    )
    evidence = result.browser_evidence or {}
    return {
        "ok": result.ok,
        "state": "completed"
        if result.ok
        else "human_gate"
        if evidence.get("human_gate")
        else "refused",
        "error_code": result.error_code,
        "browser_evidence": evidence,
        "transcript_sha256": hashlib.sha256(result.transcript.encode()).hexdigest(),
        "completion_proved": result.ok,
    }

"""Helpers for the checkout clean-room smoke."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SMOKE_EVENT_NAME = "CheckoutCleanRoomSmoke"
SMOKE_EVENT_TYPE = "checkout_clean_room"
DEFAULT_ENV = "prod"
DEFAULT_PROJECT_ID = 1
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
FORBIDDEN_AMBIENT_ENV = (
    "YOKE_PG_DSN",
    "YOKE_PG_DSN_FILE",
    "YOKE_PROJECT",
    "YOKE_SCRATCH_ROOT",
    "YOKE_CONNECTED_ENV_DISABLE",
)


class SmokeError(RuntimeError):
    """Raised when the clean-room smoke cannot complete."""


@dataclass(frozen=True)
class CommandResult:
    step: str
    command: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str

    def summary(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "command": self.command,
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout_tail": tail(self.stdout),
            "stderr_tail": tail(self.stderr),
        }


def run_json(
    command: list[str],
    *,
    step: str,
    cwd: Path,
    commands: list[CommandResult],
    env: Mapping[str, str],
) -> dict[str, Any]:
    result = run(command, step=step, cwd=cwd, commands=commands, env=env)
    return json.loads(result.stdout)


def run(
    command: list[str],
    *,
    step: str,
    cwd: Path,
    commands: list[CommandResult],
    env: Mapping[str, str],
) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=dict(env),
        text=True,
        capture_output=True,
        check=False,
    )
    result = CommandResult(
        step=step,
        command=command,
        cwd=str(cwd),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    commands.append(result)
    if completed.returncode != 0:
        raise SmokeError(
            f"{step} failed with {completed.returncode}\n"
            f"stdout:\n{tail(completed.stdout)}\n"
            f"stderr:\n{tail(completed.stderr)}"
        )
    return result


def assert_clean_clone_shape(clone: Path) -> None:
    missing = []
    for rel in ("data", "projects", "data/yoke.db", "data/connected-env.json"):
        if (clone / rel).exists():
            missing.append(rel)
    if missing:
        raise SmokeError(
            "fresh clone still contains retired local authority surface(s): "
            + ", ".join(missing)
        )


def assert_status_clean_room(
    report: Mapping[str, Any],
    *,
    clone: Path,
    yoke: Path,
) -> None:
    if not report.get("ok"):
        raise SmokeError("yoke status failed: " + json.dumps(report.get("issues")))
    runtime = report.get("runtime") or {}
    origin = str(runtime.get("runtime_import_origin") or "")
    if str(clone) not in origin:
        raise SmokeError(f"runtime import did not come from clean clone: {origin}")
    actual_yoke = Path(str(runtime.get("yoke_executable") or ""))
    if actual_yoke.resolve() != yoke.resolve():
        raise SmokeError(
            f"yoke executable was not the clean venv script: {actual_yoke}"
        )
    ambient = report.get("ambient_env") or {}
    inherited = [
        key for key in FORBIDDEN_AMBIENT_ENV
        if isinstance(ambient.get(key), Mapping) and ambient[key].get("set")
    ]
    if inherited:
        raise SmokeError("forbidden ambient Yoke env leaked: " + ", ".join(inherited))


def assert_event_visible(
    response: Mapping[str, Any],
    *,
    expected_event_id: str,
) -> None:
    if not response.get("success"):
        raise SmokeError("yoke events query failed in clean clone")
    rows = (((response.get("result") or {}).get("rows")) or [])
    if not rows:
        raise SmokeError("yoke events query did not return the smoke event")
    envelope = rows[0].get("envelope") or ""
    if expected_event_id not in envelope:
        raise SmokeError("latest smoke event did not match direct Python event id")


def isolated_env(
    *,
    home: Path,
    machine_home: Path,
    config_path: Path,
    venv_bin: Path,
    env_name: str,
    session_id: str,
) -> dict[str, str]:
    return {
        "HOME": str(home),
        "PATH": f"{venv_bin}:{BASE_PATH}",
        "YOKE_MACHINE_HOME": str(machine_home),
        "YOKE_MACHINE_CONFIG_FILE": str(config_path),
        "YOKE_ENV": env_name,
        "YOKE_SESSION_ID": session_id,
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


def base_env(home: Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "PATH": BASE_PATH,
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


def direct_python_probe() -> str:
    return r'''
import json
import logging
import os
import sys
from yoke_core.domain import db_backend, events

logging.basicConfig(level=logging.DEBUG)
project_id = int(os.environ["SMOKE_PROJECT_ID"])
event_name = os.environ["SMOKE_EVENT_NAME"]
event_type = os.environ["SMOKE_EVENT_TYPE"]
session_id = os.environ["YOKE_SESSION_ID"]

conn = db_backend.connect()
try:
    row = conn.execute(
        """
        SELECT p.slug, p.public_item_prefix, i.project_sequence, i.id, i.title
        FROM items i
        JOIN projects p ON p.id = i.project_id
        WHERE i.project_id = %s
        ORDER BY i.id ASC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
finally:
    conn.close()
if row is None:
    raise SystemExit(f"no items found for project_id={project_id}")

project_slug = str(row[0])
prefix = str(row[1] or "")
sequence = int(row[2])
item_id = int(row[3])
title = str(row[4] or "")
result = events.emit_event(
    event_name,
    event_kind="smoke",
    event_type=event_type,
    source_type="backend",
    session_id=session_id,
    severity="INFO",
    outcome="completed",
    project=project_slug,
    context={
        "project_id": project_id,
        "item_id": item_id,
        "proof": "checkout-clean-room-smoke",
    },
)
print(json.dumps({
    "project": project_slug,
    "item_id": item_id,
    "item_ref": f"{prefix}-{sequence}",
    "title": title,
    "event_id": result.event_id,
    "write_ok": result.ok,
    "write_reason": result.reason,
}))
if not result.ok:
    sys.exit(1)
'''


def tail(value: str, *, max_lines: int = 40) -> str:
    lines = value.splitlines()
    return "\n".join(lines[-max_lines:])

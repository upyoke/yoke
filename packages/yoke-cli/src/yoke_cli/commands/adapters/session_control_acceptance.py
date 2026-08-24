"""Local CLI adapter for the source-bound Fleet acceptance runner."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import List

from yoke_contracts.install_binding import is_yoke_source_checkout
from yoke_contracts.session_execution import is_subagent_execution
from yoke_contracts.uv_project import UV_EXECUTABLE, uv_project_root, uv_run_argv


ACCEPTANCE_RUN_USAGE = (
    "yoke session-control acceptance run --project P --release-sha SHA "
    "--run-id RUN --bindings-stdin [--qualification-candidate] [--preview] "
    "[--timeout-seconds N] [--poll-seconds N] "
    "[--unsupported-observation-seconds N]"
)
_RUNTIME_MODULE = "runtime.api.tools.session_control_live_acceptance_command"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yoke session-control acceptance run",
        description=(
            "Run the canonical six-cell production acceptance or stage candidate "
            "qualification from a clean, release-bound Yoke source checkout. "
            "Bindings are read only by the runner."
        ),
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--bindings-stdin", action="store_true", required=True)
    parser.add_argument("--qualification-candidate", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--poll-seconds", type=float)
    parser.add_argument("--unsupported-observation-seconds", type=float)
    return parser


def _refuse(code: str) -> int:
    print(
        json.dumps(
            {
                "schema": 1,
                "kind": "fleet_session_control_acceptance_command",
                "status": "refused",
                "failure_code": code,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 2


def _runtime_args(parsed: argparse.Namespace) -> list[str]:
    forwarded = [
        "--project",
        parsed.project,
        "--release-sha",
        parsed.release_sha,
        "--run-id",
        parsed.run_id,
        "--bindings-stdin",
    ]
    if parsed.preview:
        forwarded.append("--preview")
    if parsed.qualification_candidate:
        forwarded.append("--qualification-candidate")
    for flag, value in (
        ("--timeout-seconds", parsed.timeout_seconds),
        ("--poll-seconds", parsed.poll_seconds),
        ("--unsupported-observation-seconds", parsed.unsupported_observation_seconds),
    ):
        if value is not None:
            forwarded.extend((flag, str(value)))
    return forwarded


def session_control_acceptance_run(args: List[str]) -> int:
    parsed = _parser().parse_args(args)
    if is_subagent_execution():
        return _refuse("top_level_session_required")
    cwd = Path.cwd().resolve()
    project_root = uv_project_root(cwd)
    if project_root is None or not is_yoke_source_checkout(project_root):
        return _refuse("source_checkout_required")
    project_root = project_root.resolve()
    if shutil.which(UV_EXECUTABLE) is None:
        return _refuse("acceptance_runtime_unavailable")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    command = uv_run_argv(["-m", _RUNTIME_MODULE, *_runtime_args(parsed)])
    try:
        completed = subprocess.run(
            command,
            cwd=str(project_root),
            env=environment,
            check=False,
        )
    except OSError:
        return _refuse("acceptance_runtime_unavailable")
    return int(completed.returncode)


__all__ = ["ACCEPTANCE_RUN_USAGE", "session_control_acceptance_run"]

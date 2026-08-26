"""A background-launched worker identifies itself with no override.

The launch relay hands ``claude --bg`` to a daemon that already owns the
processes the worker's shells descend from, so the relay can neither
stamp the worker's own id at spawn (``--bg`` mints it) nor anchor it (the
daemon's spare processes are pooled and reused). What does arrive is the
harness's own per-conversation stamp. These tests spawn a real
subprocess carrying exactly the environment a launched worker gets — no
``--session-id``, no anchor registry — and assert the session-scoped
surfaces that used to fail there now resolve.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_harness.session_relay_environment import native_session_environment


WORKER_SESSION_ID = "11111111-2222-3333-4444-555555555555"

_PROBE = """
import json
from yoke_core.domain.project_scratch_dir import mint_watcher_capture_pair
from yoke_core.domain import session_ambient_identity

# This Python child still has pytest's process tree above it. Pin the
# harness family the probe models: a real launched Claude worker.
session_ambient_identity.nearest_harness_family = lambda: "claude-code"

raw, _progress = mint_watcher_capture_pair("pytest", project="yoke")
print(json.dumps({
    "session_id": session_ambient_identity.resolve_ambient_session_id(),
    "watcher_capture": str(raw),
}))
"""


def _worker_environment(tmp_path: Path) -> dict[str, str]:
    """The environment a launched Claude worker actually runs under.

    Built through the relay's own sanitizer so the test cannot drift from
    what the relay hands the child, then stamped the way Claude Code
    stamps every subprocess of a background agent.
    """
    machine_home = tmp_path / "machine-home"
    machine_home.mkdir(parents=True, exist_ok=True)
    environment = native_session_environment(
        executor="claude-code",
        executor_version="2.1.241",
        provider="anthropic",
        markers={"CLAUDE_CODE_ENTRYPOINT": "cli"},
        environ={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path / "home"),
            # The launching session's identity, which must not survive.
            "CLAUDE_CODE_SESSION_ID": "99999999-9999-9999-9999-999999999999",
            "YOKE_SESSION_ID": "88888888-8888-8888-8888-888888888888",
        },
    )
    environment.update(
        {
            "CLAUDECODE": "1",
            "CLAUDE_CODE_SESSION_ID": WORKER_SESSION_ID,
            "YOKE_MACHINE_HOME": str(machine_home),
            "YOKE_SCRATCH_ROOT": str(tmp_path / "scratch"),
            "YOKE_RUN_ID": "run-1",
        }
    )
    return environment


def test_relay_strips_the_launching_sessions_identity(tmp_path: Path) -> None:
    """A worker that inherited the launcher's id would act as the launcher."""
    environment = native_session_environment(
        executor="claude-code",
        executor_version="2.1.241",
        environ={name: "launching-session" for name in AMBIENT_ENV_VARS},
    )

    assert not [name for name in AMBIENT_ENV_VARS if name in environment]


def _run_probe(tmp_path: Path) -> dict[str, str]:
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env=_worker_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        pytest.fail(f"worker probe failed: {completed.stderr[-2000:]}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_spawned_worker_resolves_its_session_without_an_override(
    tmp_path: Path,
) -> None:
    assert _run_probe(tmp_path)["session_id"] == WORKER_SESSION_ID


def test_spawned_worker_mints_captures_under_its_own_session(
    tmp_path: Path,
) -> None:
    """Captures used to land under the unknown-session placeholder, a path
    the session-cwd guard then refused for the very session that made it."""
    capture = Path(_run_probe(tmp_path)["watcher_capture"])

    scratch_root = (tmp_path / "scratch").resolve()

    assert capture.resolve().relative_to(scratch_root).parts[:6] == (
        "yoke",
        "sessions",
        WORKER_SESSION_ID,
        "runs",
        "run-1",
        "watcher-captures",
    )
    assert "session-unknown" not in str(capture)

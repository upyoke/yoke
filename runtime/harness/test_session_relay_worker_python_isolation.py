"""The relay's own Python reaches its supervisor and stops at the native.

Both halves are one real process chain, because each half is a claim about
what an actual subprocess received: the supervisor starts on an interpreter
that finds the running release only through the inherited import path, and
the native it starts must find nothing of that release at all — a project
command inside that native otherwise treats the relay's release directory as
the environment of the project it is working in, and installs into it.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from yoke_cli.config.session_relay_instance import RELAY_STATE_DIR_ENV
from yoke_harness import session_relay_codex_app_server_client as app_server_module
from yoke_harness import session_relay_codex_cli as codex_cli_module
from yoke_harness import session_relay_native_models as native_models_module
from yoke_harness import session_relay_native_spawn
from yoke_harness import session_relay_plan_limits as plan_limits_module
from yoke_harness import session_relay_surface_probes as surface_probes_module
from yoke_harness.session_relay_codex import CodexNativeRequest
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_inventory import ResolvedNativeCli
from yoke_harness.session_relay_native_streams import BoundedStreams


PROJECT_BIN = "/Users/example/project/.venv/bin"
MACHINE_LAUNCHER_BIN = "/Users/example/.local/bin"


def _relay_state_dir(tmp_path: Path) -> Path:
    """A relay tree shaped like an installed one, with packages to lose."""
    state_dir = tmp_path / "relay-instance"
    (state_dir / "runtime" / "bin").mkdir(parents=True)
    (state_dir / "venv").symlink_to(state_dir / "runtime", target_is_directory=True)
    packages = state_dir / "releases" / "deadbeef" / "lib" / "python" / "yoke_cli"
    packages.mkdir(parents=True)
    (packages / "__init__.py").write_text("", encoding="utf-8")
    return state_dir


def _import_path_probe(tmp_path: Path) -> tuple[Path, Path]:
    """An import-path entry that records every Python process that reads it."""
    probe_root = tmp_path / "import-path-probe"
    probe_root.mkdir()
    marker = tmp_path / "python-startups"
    (probe_root / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        f"with Path({str(marker)!r}).open('a', encoding='utf-8') as handle:\n"
        "    handle.write(f'{os.getpid()}\\n')\n",
        encoding="utf-8",
    )
    return probe_root, marker


def _native_account(tmp_path: Path, release_packages: Path) -> tuple[list[str], Path]:
    """A stand-in foreign CLI that reports its environment and acts on it.

    The write is the incident in miniature: a project command that finds an
    active virtual environment installs into it, and the environment it found
    was the relay's.
    """
    account = tmp_path / "native-environment.json"
    script = tmp_path / "native.sh"
    script.write_text(
        'if [ -n "$VIRTUAL_ENV" ]; then\n'
        f'  echo replaced > "{release_packages}/__init__.py"\n'
        "fi\n"
        f'printf \'{{"PATH":"%s","VIRTUAL_ENV":"%s","PYTHONPATH":"%s",'
        f'"{RELAY_STATE_DIR_ENV}":"%s"}}\' '
        f'"$PATH" "$VIRTUAL_ENV" "$PYTHONPATH" "${RELAY_STATE_DIR_ENV}" '
        f'> "{account}"\n',
        encoding="utf-8",
    )
    return ["/bin/sh", str(script)], account


def test_the_relay_python_reaches_the_supervisor_and_stops_at_the_native(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _relay_state_dir(tmp_path)
    release = state_dir / "releases" / "deadbeef"
    release_packages = release / "lib" / "python" / "yoke_cli"
    probe_root, python_startups = _import_path_probe(tmp_path)
    native, account = _native_account(tmp_path, release_packages)
    import_path = os.pathsep.join(
        [str(probe_root), *(entry for entry in sys.path if entry)]
    )
    environment = native_session_environment(
        executor="cursor",
        environ={
            **os.environ,
            "PATH": os.pathsep.join(
                [
                    str(state_dir / "venv" / "bin"),
                    str(state_dir / "runtime" / "bin"),
                    MACHINE_LAUNCHER_BIN,
                    PROJECT_BIN,
                    "/usr/bin",
                    "/bin",
                ]
            ),
            "VIRTUAL_ENV": str(release),
            "PYTHONPATH": import_path,
            RELAY_STATE_DIR_ENV: str(state_dir),
        },
    )
    monkeypatch.setattr(
        session_relay_native_spawn,
        "record_supervised_native",
        lambda *_args, **_kwargs: True,
    )

    started = session_relay_native_spawn.spawn_supervised_native(
        native,
        checkout=tmp_path,
        environment=environment,
        attempt_id=str(uuid4()),
        native_session_id=None,
        binary_source="path",
        state_dir=tmp_path / "native-state",
    )

    assert started is not None
    _pid, wait_status = os.waitpid(started.pid, 0)
    assert os.waitstatus_to_exitcode(wait_status) == 0

    # The supervisor is a Python process and read the inherited import path;
    # the native is not, so the one recorded startup is the supervisor's.
    assert python_startups.read_text(encoding="utf-8").split() != []

    observed = json.loads(account.read_text(encoding="utf-8"))
    assert observed["VIRTUAL_ENV"] == ""
    assert observed["PYTHONPATH"] == ""
    assert observed[RELAY_STATE_DIR_ENV] == ""
    assert observed["PATH"].split(os.pathsep) == [
        MACHINE_LAUNCHER_BIN,
        PROJECT_BIN,
        "/usr/bin",
        "/bin",
    ]
    # The release the relay is running is exactly as it was: with no active
    # environment to install into, the native had nowhere to write.
    assert (release_packages / "__init__.py").read_text(encoding="utf-8") == ""


class _SpawnRecorder:
    """Stand in for the vendor binary and keep the environment it was given."""

    def __init__(self) -> None:
        self.environment: dict[str, str] = {}

    def __call__(self, _command, **kwargs):
        self.environment = dict(kwargs["env"])
        return _StartedBinary()

    def completed(self, _command, **kwargs):
        self.environment = dict(kwargs["env"])
        return subprocess.CompletedProcess([], 0, "", "")


class _StartedBinary:
    """The narrow surface each caller touches before it reads any output.

    ``stdout`` is a real pipe because one caller registers it with a
    selector, which needs a file descriptor rather than a buffer.
    """

    pid = 4242
    stderr = None
    returncode: int | None = None

    def __init__(self) -> None:
        read_fd, self._write_fd = os.pipe()
        self.stdin = io.BytesIO()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode


def _relay_daemon_environment(monkeypatch: pytest.MonkeyPatch, state_dir: Path) -> None:
    """Put this process in the relay's own environment, as a relay child is."""
    monkeypatch.setenv("VIRTUAL_ENV", str(state_dir / "releases" / "deadbeef"))
    monkeypatch.setenv("PYTHONPATH", str(state_dir / "releases" / "deadbeef" / "lib"))
    monkeypatch.setenv(RELAY_STATE_DIR_ENV, str(state_dir))
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join([str(state_dir / "venv" / "bin"), PROJECT_BIN, "/usr/bin"]),
    )


def _assert_relay_python_absent(environment: dict[str, str]) -> None:
    assert "VIRTUAL_ENV" not in environment
    assert "PYTHONPATH" not in environment
    assert RELAY_STATE_DIR_ENV not in environment
    assert environment["PATH"].split(os.pathsep) == [PROJECT_BIN, "/usr/bin"]


def test_the_codex_turn_binary_starts_without_the_relay_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _relay_state_dir(tmp_path)
    _relay_daemon_environment(monkeypatch, state_dir)
    recorder = _SpawnRecorder()
    monkeypatch.setattr(codex_cli_module.subprocess, "Popen", recorder)
    monkeypatch.setattr(
        codex_cli_module,
        "resolve_native_cli_source",
        lambda _name: ResolvedNativeCli("/opt/codex/bin/codex", "path"),
    )

    codex_cli_module.CodexCliTransport(worker=True)._spawn(
        CodexNativeRequest(
            job_kind="launch",
            job_id="launch-1",
            surface="codex-cli",
            surface_version="0.149.0",
            checkout=tmp_path,
            requested_model=None,
            presentation=None,
            target_liveness=None,
            target_session_id=None,
            wake_mode=None,
            instruction_id="launch:1",
            native_instruction="do the work",
            launch_attestation="secret",
        ),
        resume=False,
        streams=BoundedStreams(),
    )

    _assert_relay_python_absent(recorder.environment)


def test_the_codex_app_server_binary_starts_without_the_relay_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = _relay_state_dir(tmp_path)
    _relay_daemon_environment(monkeypatch, state_dir)
    recorder = _SpawnRecorder()
    monkeypatch.setattr(app_server_module.subprocess, "Popen", recorder)
    monkeypatch.setattr(
        app_server_module, "resolve_native_cli", lambda _name: "/opt/codex/bin/codex"
    )
    monkeypatch.setattr(app_server_module._Client, "request", lambda *_a, **_k: {})
    monkeypatch.setattr(app_server_module._Client, "notify", lambda *_a, **_k: None)

    app_server_module._Client("codex", tmp_path, dict(os.environ), 1.0)

    _assert_relay_python_absent(recorder.environment)


def test_the_installed_surface_probes_run_without_the_relay_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probes read a vendor binary too, and one had no environment at all."""
    state_dir = _relay_state_dir(tmp_path)
    _relay_daemon_environment(monkeypatch, state_dir)
    recorder = _SpawnRecorder()
    monkeypatch.setattr(
        surface_probes_module, "resolve_native_cli", lambda _name: "/opt/cursor/bin/x"
    )
    monkeypatch.setattr(
        native_models_module, "resolve_native_cli", lambda _name: "/opt/cursor/bin/x"
    )
    monkeypatch.setattr(
        plan_limits_module, "resolve_native_cli", lambda _name: "/opt/cursor/bin/x"
    )
    monkeypatch.setattr(native_models_module.subprocess, "run", recorder.completed)
    monkeypatch.setattr(plan_limits_module.subprocess, "run", recorder.completed)

    surface_probes_module.probe_cli_surface(
        "cursor-cli", ("cursor-agent", "--version"), runner=recorder.completed
    )
    _assert_relay_python_absent(recorder.environment)

    recorder.environment = {}
    native_models_module.probe_cursor_cli_models(observed_at="2026-01-01T00:00:00Z")
    _assert_relay_python_absent(recorder.environment)

    recorder.environment = {}
    plan_limits_module._cursor_tier_from_cli()
    _assert_relay_python_absent(recorder.environment)

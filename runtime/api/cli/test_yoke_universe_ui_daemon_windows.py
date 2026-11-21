"""The ``yoke ui`` daemon starts through the platform's operator launcher.

On Windows the extensionless ``yoke`` beside ``yoke.cmd`` is a ``sh``
script that ``CreateProcess`` cannot run. The real-process case spawns
the published ``yoke.cmd`` shape through the unstubbed start path, with a
launcher that keeps the production hop (cmd.exe, then a launcher Python,
then the serving Python), and proves ``yoke ui down`` leaves none of them.
"""

from __future__ import annotations

from pathlib import Path
import sys
import time

import psutil
import pytest

from runtime.api.cli.yoke_universe_ui_daemon_test_support import (
    CHILD_SCRIPT,
    _free_port,
)
from yoke_cli.config import cli_release_runtime
from yoke_cli.config import universe_ui_daemon as daemon
from yoke_cli.config import universe_ui_daemon_state as state
from yoke_cli.config import universe_ui_launchd as launchd


pytestmark = pytest.mark.windows

# Mirrors the release launcher: it runs the CLI as a child and exits with
# its code. Only `ui serve-process` is served, from the argv the daemon built.
LAUNCHER = f"""
import subprocess, sys
argv = sys.argv[1:]
assert argv[0] == "--env" and argv[2:5] == ["ui", "serve-process", "--host"], argv
assert argv[6] == "--port", argv
serve = {CHILD_SCRIPT!r}
sys.exit(subprocess.call([sys.executable, "-c", serve, argv[5], argv[7], argv[1]]))
"""


@pytest.fixture()
def machine_home(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def test_windows_child_runs_yoke_cmd_while_launchd_keeps_the_shim(monkeypatch):
    monkeypatch.setattr(launchd, "_shim_path", lambda environ=None: Path("/opt/bin/yoke"))
    monkeypatch.setattr(cli_release_runtime, "WINDOWS", True)
    command = launchd.child_command(host="127.0.0.1", port=8688, env="local")
    assert command[0] == str(Path("/opt/bin/yoke.cmd"))
    assert command[1:] == [
        "--env", "local", "ui", "serve-process", "--host", "127.0.0.1", "--port", "8688",
    ]
    document = launchd.plist_document(
        host="127.0.0.1", port=8688, env="local", log_path=Path("/tmp/ui.log"),
    )
    assert document["ProgramArguments"][0] == str(Path("/opt/bin/yoke"))


@pytest.mark.parametrize("env", ["a b", "x&y", "%PATH%", 'q"', "", "dev.1"])
def test_up_refuses_an_env_name_the_launcher_cannot_pass(machine_home, env):
    with pytest.raises(state.UiDaemonError, match="ui_env_name_unsupported"):
        daemon.up(host="127.0.0.1", port=_free_port(), env=env)
    assert not state.record_path().exists()


def _gone_within(processes, seconds: float) -> list:
    deadline = time.monotonic() + seconds
    while True:
        alive = [p for p in processes if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]
        if not alive or time.monotonic() >= deadline:
            return alive
        time.sleep(0.05)


@pytest.mark.windows_only(reason="cmd.exe runs the yoke.cmd launcher")
def test_up_and_down_through_the_real_yoke_cmd(monkeypatch, tmp_path, machine_home):
    root, bin_dir = tmp_path / "cli root", tmp_path / "tool bin"
    root.mkdir()
    bin_dir.mkdir()
    (root / "launcher").write_text(LAUNCHER, encoding="utf-8")
    for path, content in cli_release_runtime._shims(root, Path(sys.executable), bin_dir).items():
        path.write_bytes(content.encode())
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(bin_dir))
    monkeypatch.setattr(launchd, "supported", lambda: False)
    monkeypatch.setattr(launchd, "agent_installed", lambda: False)
    spawned = []
    real_spawn = daemon.platform_process.spawn_group

    def observe(*args, **kwargs):
        spawned.append(real_spawn(*args, **kwargs))
        return spawned[-1]

    monkeypatch.setattr(daemon.platform_process, "spawn_group", observe)
    port = _free_port()
    assert launchd.child_command(host="127.0.0.1", port=port, env="local")[0] == str(
        bin_dir / "yoke.cmd"
    )

    started = daemon.up(host="127.0.0.1", port=port, env="local")
    try:
        assert started["started"] is True and started["serving"] is True
        shell = psutil.Process(spawned[0].pid)
        assert shell.name().lower() == "cmd.exe"
        chain = [shell, *shell.children(recursive=True)]
        assert started["pid"] in {p.pid for p in chain}
    finally:
        stopped = daemon.down()

    assert stopped["stopped"] is True
    assert _gone_within(chain, 5.0) == []
    assert state.port_accepting("127.0.0.1", port) is False
    again = daemon.up(host="127.0.0.1", port=port, env="local")
    daemon.down()
    assert again["started"] is True

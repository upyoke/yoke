"""The started relay names the tree it owns, beside the state it exports.

The variables that point a relay child at the running release are set in one
place, and the root they belong to is set there with them. A child that hands
off to a foreign CLI then drops exactly the relay's own directories from that
child's search path — without that declaration it would have to infer the root
from the shape of a release path, and be wrong the moment the layout moves.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import sysconfig

from yoke_cli.config.session_relay_instance import RELAY_STATE_DIR_ENV
from yoke_core.tools.session_relay_release import RELAY_ACTIVE_RELEASE_NAME
from yoke_core.tools.session_relay_runtime_install import _install_runtime_entrypoint


def _release_packages_relative() -> Path:
    """Where this interpreter keeps packages, relative to its own prefix."""
    return Path(sysconfig.get_path("purelib")).resolve().relative_to(
        Path(sys.prefix).resolve()
    )


def _installed_relay(tmp_path: Path) -> Path:
    """One relay state directory with a launcher and a release to select."""
    state_dir = tmp_path / "relay-instance"
    runtime = state_dir / "runtime"
    (runtime / "bin").mkdir(parents=True)
    release = state_dir / "releases" / "deadbeef"
    packages = release / _release_packages_relative()
    (packages / "yoke_cli").mkdir(parents=True)
    (packages / "yoke_cli" / "__init__.py").write_text("", encoding="utf-8")
    (packages / "yoke_cli" / "main.py").write_text(
        "import json, os, sys\n"
        "def main(_argv):\n"
        "    print(json.dumps({name: os.environ.get(name, '') for name in "
        f"('VIRTUAL_ENV', 'PYTHONPATH', {RELAY_STATE_DIR_ENV!r})}}))\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (state_dir / RELAY_ACTIVE_RELEASE_NAME).symlink_to(release, target_is_directory=True)
    _install_runtime_entrypoint(runtime, state_dir=state_dir)
    return state_dir


def test_the_started_relay_exports_the_root_of_its_own_tree(tmp_path: Path) -> None:
    state_dir = _installed_relay(tmp_path)
    release = (state_dir / RELAY_ACTIVE_RELEASE_NAME).resolve()

    completed = subprocess.run(
        [sys.executable, str(state_dir / "runtime" / "bin" / "yoke")],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    exported = json.loads(completed.stdout)
    assert exported["VIRTUAL_ENV"] == str(release)
    assert exported["PYTHONPATH"] == str(release / _release_packages_relative())
    # Not the release, and not inferred from it: the directory the relay's
    # launch link, runtime and releases all live under.
    assert exported[RELAY_STATE_DIR_ENV] == str(state_dir)

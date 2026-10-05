"""Consumer CI can mint watcher captures without control-plane authority."""

import os
import subprocess
import sys


def test_slug_project_mints_pytest_captures_without_a_connection(tmp_path):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("YOKE_", "PG", "CLAUDE", "CURSOR", "CODEX"))
    }
    env.update(
        YOKE_PROJECT="platform",
        YOKE_MACHINE_HOME=str(tmp_path / "machine"),
        YOKE_MACHINE_CONFIG_FILE=str(tmp_path / "absent-config.json"),
        YOKE_SCRATCH_ROOT=str(tmp_path / "scratch"),
    )
    script = """
from pathlib import Path
from yoke_core.domain import db_helpers
from yoke_core.domain import project_scratch_identity as identity
from yoke_core.tools import watch_pytest

def forbidden(*args, **kwargs):
    raise AssertionError('offline capture naming touched the control plane')

db_helpers.connect = forbidden
identity.relay = forbidden
watch_pytest._impacted_tree = lambda: Path.cwd()
watch_pytest._impacted_selection = lambda *args, **kwargs: None
raise SystemExit(watch_pytest.main(['--impacted', 'main', '--bounded']))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    captures = list((tmp_path / "scratch" / "platform").rglob("*.log"))
    assert len(captures) == 2
    progress = next(path for path in captures if ".progress." in path.name)
    assert progress.read_text().startswith("# watch_pytest writer_pid=")
    assert progress.read_text().rstrip().endswith("# watch_pytest exit=0")

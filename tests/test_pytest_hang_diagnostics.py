"""Hang diagnostics escape xdist capture into the CI output stream."""

from pathlib import Path
import subprocess
import sys
import tomllib

import pytest


CONFIG = Path(__file__).resolve().parents[1] / "pyproject.toml"


@pytest.mark.parametrize("slow", [True, False], ids=["hang-dump", "normal-test"])
def test_worker_stack_dump_reaches_output(tmp_path, slow):
    test = tmp_path / "test_worker_sleep.py"
    test.write_text(
        "import time\n"
        "def test_sleeping_worker():\n"
        f"    time.sleep({1 if slow else 0})\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(CONFIG),
        "--confcutdir",
        str(tmp_path),
        "-n",
        "1",
        "-q",
    ]
    if slow:
        command.extend(["-o", "faulthandler_timeout=0.1"])
    command.append(str(test))
    result = subprocess.run(
        command,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "1 passed" in result.stdout
    if slow:
        assert "Timeout (" in result.stdout
        assert "test_sleeping_worker" in result.stdout
        assert str(test) in result.stdout
    else:
        assert "Timeout (" not in result.stdout


def test_shared_timeout_has_ci_headroom():
    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    timeout = config["tool"]["pytest"]["ini_options"]["faulthandler_timeout"]
    assert 3 * 153.4 < timeout < 35 * 60

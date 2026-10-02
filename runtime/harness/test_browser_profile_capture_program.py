"""The standalone host capture keeps private-directory creation dependency-free."""

import os
import shlex
import subprocess
from types import SimpleNamespace

from yoke_harness.ssh_browser_profile_capture import capture_browser_profile


def test_standalone_capture_program_creates_private_ancestors(tmp_path):
    destination = tmp_path / "new" / "nested"

    def run(command, *, timeout):
        argv = shlex.split(command)
        assert argv[:2] == ["python3", "-c"]
        assert timeout == 300
        namespace = {"__name__": "standalone_capture"}
        exec(compile(argv[2], "standalone-capture", "exec"), namespace)
        previous = os.umask(0o002)
        try:
            namespace["create_private_directory"](destination)
        finally:
            os.umask(previous)
        return subprocess.CompletedProcess(argv, 0, '{"ok":true}', "")

    result = capture_browser_profile(
        SimpleNamespace(project="project", golden_destination="/goldens/browser"),
        SimpleNamespace(home="/home/test", _run=run),
    )
    assert result.ok
    assert destination.stat().st_mode & 0o777 == 0o700
    assert destination.parent.stat().st_mode & 0o777 == 0o700

"""Git and JSON reads for isolated project retirement tests."""

import json
import subprocess


def git(root, *args):
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def read_json(path):
    return json.loads(path.read_text())

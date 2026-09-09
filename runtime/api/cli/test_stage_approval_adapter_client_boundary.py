"""The stage-approval operator command survives a client-only install."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from runtime.api.product_boundary_isolation import client_only_env


def test_stage_approval_adapter_imports_without_core(tmp_path: Path) -> None:
    """A public command must survive on a client-only install.

    This adapter resolves the plane that must run its operation before it
    dispatches. Resolving that through the engine would fail on import,
    on exactly the installs that carry only contracts and textual — so the
    resolver lives in the CLI transport and the engine delegates to it.
    """
    script = """
import json
import sys
from yoke_cli.commands.adapters.deployment_stage_approval import (
    deployment_runs_stage_approval_evaluate,
)
from yoke_cli.transport.serving_plane import serving_control_plane_env
forbidden = sorted(
    name for name in sys.modules
    if name == "runtime" or name.startswith("runtime.")
    or name == "yoke_core" or name.startswith("yoke_core.")
)
print(json.dumps(forbidden))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/tmp",
        env=client_only_env(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == []

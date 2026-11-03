"""``yoke hook evaluate`` answers before the command catalog loads.

Every harness tool call pays this process's start-up twice, so the resident
round trip must not import the registry, its adapters or pydantic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


_PROBE = """
import io, json, sys
import yoke_cli.hook_resident_client as resident_client

resident_client.evaluate_with_resident = lambda *a, **k: (
    resident_client.ResidentEvaluation(stdout="ok", stderr="", exit_code=0)
)
sys.stdin = io.StringIO("{}")
from yoke_cli.main import main

code = main(["hook", "evaluate", "PreToolUse"])
heavy = [
    name
    for name in (
        "yoke_cli.command_router", "yoke_cli.commands.registry", "pydantic",
        "httpx", "ssl", "urllib.request", "textual", "boto3", "sqlalchemy",
        "importlib.metadata", "yoke_contracts.hook_runner.safety",
    )
    if name in sys.modules
]
print(json.dumps({"code": code, "heavy": heavy}), file=sys.stderr)
"""


def test_resident_round_trip_does_not_import_the_command_registry() -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTEST_CURRENT_TEST", "YOKE_HOOK_CONFIG_OWNER"}
    }
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "ok"
    report = json.loads(completed.stderr.strip().splitlines()[-1])
    assert report == {"code": 0, "heavy": []}


def test_importing_hook_entry_does_not_load_fallback_dependencies() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", """
import sys
import yoke_cli.main
import yoke_cli.commands.adapters.hooks
assert not any(name in sys.modules for name in (
    "yoke_cli.command_router", "yoke_cli.commands.registry", "pydantic",
    "httpx", "ssl", "urllib.request", "textual", "boto3", "sqlalchemy",
    "importlib.metadata", "yoke_cli.config.machine_config",
    "yoke_contracts.hook_runner.safety",
))
"""],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

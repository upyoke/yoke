"""Execute a profile-only golden capture under the existing host lease."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
from typing import Any

from yoke_contracts.machine_config.capability_secrets import (
    browser_profile_relative_path,
)
from yoke_contracts.machine_config.schema import SECRETS_DIR_NAME
from yoke_contracts.machine_qa_execution import HostControlExecutionContract
from yoke_harness import browser_profile_archive
from yoke_harness.test_machine_types import HostActionResult


def capture_browser_profile(
    contract: HostControlExecutionContract, control: Any
) -> HostActionResult:
    if contract.settings["os"] != "linux":
        return HostActionResult(False, {}, "browser_profile_os_unsupported")
    relative = str(
        Path(".yoke")
        / SECRETS_DIR_NAME
        / browser_profile_relative_path(contract.project)
    )
    command = shlex.join(
        [
            "/usr/bin/python3",
            "-c",
            Path(browser_profile_archive.__file__).read_text(),
            "capture",
            control.home,
            contract.golden_destination,
            contract.project,
            relative,
        ]
    )
    result = control._run(command, timeout=300)
    try:
        evidence = json.loads(result.stdout)
        ok = (
            result.returncode == 0
            and isinstance(evidence, dict)
            and evidence.get("ok") is True
        )
    except (ValueError, TypeError):
        evidence, ok = {}, False
    if not isinstance(evidence, dict):
        evidence = {}
    if not ok:
        evidence["recovery"] = (
            "Log out of the desktop and stop the browser daemon; keep the profile intact and retry a new sibling snapshot before any reset."
        )
    return HostActionResult(
        ok,
        evidence,
        None if ok else evidence.get("reason", "browser_profile_capture_failed"),
    )

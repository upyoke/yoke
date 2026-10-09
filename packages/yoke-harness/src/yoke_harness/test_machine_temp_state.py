"""Leased baseline cleanup and mission disk admission using the host adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness import test_machine_temp_script
from yoke_harness.test_machine_types import HostActionResult


RECOVERY = (
    "Finish or abort the owning mission, then run `yoke test-machine reset "
    "--project PROJECT --machine MACHINE`; expand the host disk if reset "
    "cannot restore the declared minimum free space, and retry QA."
)


def _run(control: Any, operation: str) -> dict:
    protected = [
        str(value)
        for key in ("golden_baseline_path", "browser_profile_baseline_path")
        if (value := getattr(control, key, None))
    ]
    # macOS seals its manifest and probes beside the golden directory.
    golden = getattr(control, "golden_baseline_path", None)
    if golden:
        protected.extend([golden + ".manifest", golden + ".probes"])
    protected.extend(getattr(control, "baseline_preserved_temp_paths", ()))
    source = Path(test_machine_temp_script.__file__).read_text(encoding="utf-8")
    result = control.run_command(
        ["/usr/bin/python3", "-c", source, operation, control.home, *protected],
        timeout=120,
    )
    try:
        receipt = json.loads(result.stdout)
        if not isinstance(receipt, dict) or not isinstance(receipt.get("ok"), bool):
            raise ValueError("missing operation outcome")
    except (TypeError, ValueError):
        receipt = {"ok": False, "error_code": "test_machine_temp_receipt_invalid"}
    if result.returncode and receipt["ok"]:
        receipt = {"ok": False, "error_code": "test_machine_temp_operation_failed"}
    if not receipt["ok"]:
        receipt["recovery"] = RECOVERY
    return receipt


def clear_baseline_temp_state(control: Any) -> HostActionResult:
    """Called under exclusive admission after restoring the declared home."""
    try:
        receipt = _run(control, "cleanup")
    except Exception:
        receipt = {
            "ok": False,
            "error_code": "test_machine_temp_operation_failed",
            "recovery": RECOVERY,
        }
    return HostActionResult(
        receipt["ok"], {"temp_cleanup": receipt}, receipt.get("error_code")
    )


def require_mission_disk_space(control: Any) -> dict:
    """Refuse before packages or mission scratch can consume a full disk."""
    receipt = _run(control, "disk")
    if not receipt["ok"]:
        raise HostControlLocalError(
            code=receipt.get("error_code") or "test_machine_disk_preflight_failed",
            phase="disk_preflight",
            detail=f"Test Machine disk admission refused: {receipt}",
            recovery_hint=RECOVERY,
        )
    return receipt

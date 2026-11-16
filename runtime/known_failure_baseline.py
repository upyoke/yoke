"""Shrink-only known-failure baselines for the Windows and macOS suite runs.

Linux CI owns the full suite's verdict. The on-demand ``yoke-suite`` workflow
runs the same suite on Windows and macOS, where some tests do not pass yet.
Each such test is listed, with the reason, in
``runtime/known_failure_baselines/<os>.json`` and marked
``xfail(strict=True)`` on that OS only:

- a listed test that still fails is reported as xfailed;
- a listed test that now passes fails the run as XPASS(strict), so the entry
  must be deleted in the same change (the baseline only shrinks);
- an unlisted failure fails the run as usual.

Entries are pytest node ids relative to the repository root, always written
with ``/`` separators. A parametrized node id names one case; a node id
without parameters covers every case of that test.

Only runs that set ``YOKE_KNOWN_FAILURE_BASELINE=1`` (the workflow does) apply
a baseline. A developer's own Mac is not the CI runner image: a test the
runner fails may pass there, and a local run judges every test plainly.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

#: Set to ``1`` by the yoke-suite workflow to apply this OS's baseline.
ENABLE_ENV = "YOKE_KNOWN_FAILURE_BASELINE"

BASELINE_DIR = Path(__file__).resolve().parent / "known_failure_baselines"

#: The baseline file each ``sys.platform`` reads; Linux has none.
PLATFORM_BASELINES = {"win32": "windows", "darwin": "macos"}


def baseline_path(os_name: str) -> Path:
    return BASELINE_DIR / f"{os_name}.json"


def load_baseline(os_name: str) -> dict[str, str]:
    """The ``{node id: reason}`` baseline for *os_name*."""
    path = baseline_path(os_name)
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise pytest.UsageError(
            f"known_failure_baseline_unreadable: {path} ({exc}); restore it as a "
            "JSON object mapping pytest node ids to reasons"
        ) from exc
    if not isinstance(entries, dict):
        raise pytest.UsageError(
            f"known_failure_baseline_invalid: {path} must be a JSON object "
            "mapping pytest node ids to reasons"
        )
    return entries


def baseline_reason(node_id: str, entries: dict[str, str]) -> str | None:
    """The reason *node_id* is expected to fail, by exact or unparametrized id."""
    reason = entries.get(node_id)
    if reason is None and node_id.endswith("]") and "[" in node_id:
        reason = entries.get(node_id[: node_id.index("[")])
    return reason


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    os_name = PLATFORM_BASELINES.get(sys.platform)
    if os_name is None or os.environ.get(ENABLE_ENV) != "1":
        return
    entries = load_baseline(os_name)
    if not entries:
        return
    for item in items:
        reason = baseline_reason(item.nodeid, entries)
        if reason is not None:
            item.add_marker(
                pytest.mark.xfail(strict=True, reason=f"{os_name} known failure: {reason}")
            )

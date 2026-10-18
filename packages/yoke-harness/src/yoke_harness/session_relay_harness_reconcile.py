"""Refresh native inventory and reconcile setup when harness homes appear."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from yoke_contracts.harness_machine_hooks import installed_machine_hooks
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_harness.harness_setup_reconcile import (
    HarnessSetupResult,
    reconcile_harness_setup,
)
from yoke_harness.session_relay_schedule import relay_state_dir
from yoke_harness.session_relay_surface_probe_cache import refresh_surface_probe_cache

RETRY_SECONDS = 15 * 60
STATE_FILE = "harness-setup-reconcile.json"


def state_path() -> Path:
    return relay_state_dir() / STATE_FILE


def read_reconcile_state(path: Path | None = None) -> dict:
    selected = path or state_path()
    if not selected.exists():
        return {}
    try:
        doc = json.loads(selected.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("expected an object")
        return doc
    except (OSError, ValueError) as exc:
        return {
            "failure": {
                "reason": f"harness_reconcile_state_unreadable: {selected}: {exc}",
                "recovery": "Repair the relay state file, then restart the relay.",
            }
        }


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(doc, stream, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def remember_reconcile_result(result: HarnessSetupResult) -> None:
    """A doctor repair updates the same durable standing as a relay attempt."""
    path = state_path()
    state = read_reconcile_state(path)
    fingerprint = sorted(spec.harness_id for spec in installed_machine_hooks())
    failure = result.payload() if result.failed else None
    _write(
        path,
        {
            "fingerprint": state.get("fingerprint", []) if failure else fingerprint,
            "attempted_fingerprint": fingerprint,
            "attempted_at": format_instant(utc_now()),
            "retry_after": time.time() + RETRY_SECONDS if failure else 0,
            "failure": failure,
        },
    )


def reconcile_on_change(*, path: Path | None = None, now: float | None = None) -> dict:
    """Remember successful fingerprints; retry failed ones after bounded backoff."""
    selected = path or state_path()
    state = read_reconcile_state(selected)
    fingerprint = sorted(spec.harness_id for spec in installed_machine_hooks())
    if state.get("fingerprint") == fingerprint and not state.get("failure"):
        return state
    clock = time.time() if now is None else now
    if state.get("attempted_fingerprint") == fingerprint and clock < state.get(
        "retry_after", 0
    ):
        return state
    try:
        result = reconcile_harness_setup()
        failure = result.payload() if result.failed else None
    except Exception as exc:
        failure = {
            "reason": f"harness_reconcile_failed: {exc}",
            "recovery": "Run `yoke doctor run --only harness-setup --fix`.",
        }
    updated = {
        "fingerprint": state.get("fingerprint", []) if failure else fingerprint,
        "attempted_fingerprint": fingerprint,
        "attempted_at": format_instant(utc_now()),
        "retry_after": clock + RETRY_SECONDS if failure else 0,
        "failure": failure,
    }
    try:
        _write(selected, updated)
    except OSError as exc:
        raise RuntimeError(
            f"harness_reconcile_state_unwritable: {selected}: {exc}; "
            "repair relay state-directory permissions and restart the relay"
        ) from exc
    return updated


def refresh_harness_inventory() -> object:
    """The non-broker relay inventory callback; retain the probe's return value."""
    try:
        return refresh_surface_probe_cache()
    finally:
        reconcile_on_change()

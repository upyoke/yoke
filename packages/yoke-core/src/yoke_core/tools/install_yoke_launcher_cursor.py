"""Write the unattended posture into Cursor's own ``cli-config.json``.

Cursor keeps model choice, display preferences, and auth cache in the same
file as the two keys that decide whether it stops to ask before running a
command. So this pass sets only those two, only when they are absent or
already agree, and reports anything the operator has set differently rather
than overwriting it. What the keys are and why lives in
:mod:`yoke_contracts.harness_unattended_posture`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts.harness_unattended_posture import (
    CURSOR_APPROVAL_MODE,
    CURSOR_APPROVAL_MODE_KEY,
    CURSOR_SANDBOX_CONTAINER,
    CURSOR_SANDBOX_MODE,
    CURSOR_SANDBOX_MODE_KEY,
    cursor_config_path,
)


def _load(target: Path) -> Optional[Dict[str, Any]]:
    """Config object, or ``None`` when Cursor is not set up on this machine."""
    if not target.parent.is_dir():
        return None
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def plan(config: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return the config the unattended posture requires, plus what changed."""
    record: Dict[str, Any] = {"set_keys": [], "conflicts": []}
    updated = dict(config)
    current = updated.get(CURSOR_APPROVAL_MODE_KEY)
    if current is None:
        updated[CURSOR_APPROVAL_MODE_KEY] = CURSOR_APPROVAL_MODE
        record["set_keys"].append(CURSOR_APPROVAL_MODE_KEY)
    elif current != CURSOR_APPROVAL_MODE:
        record["conflicts"].append(
            f"{CURSOR_APPROVAL_MODE_KEY} = {current!r} "
            f"(Yoke needs {CURSOR_APPROVAL_MODE!r})"
        )
    sandbox = updated.get(CURSOR_SANDBOX_CONTAINER)
    sandbox = dict(sandbox) if isinstance(sandbox, dict) else {}
    mode = sandbox.get(CURSOR_SANDBOX_MODE_KEY)
    if mode is None:
        sandbox[CURSOR_SANDBOX_MODE_KEY] = CURSOR_SANDBOX_MODE
        updated[CURSOR_SANDBOX_CONTAINER] = sandbox
        record["set_keys"].append(
            f"{CURSOR_SANDBOX_CONTAINER}.{CURSOR_SANDBOX_MODE_KEY}"
        )
    elif mode != CURSOR_SANDBOX_MODE:
        record["conflicts"].append(
            f"{CURSOR_SANDBOX_CONTAINER}.{CURSOR_SANDBOX_MODE_KEY} = {mode!r} "
            f"(Yoke needs {CURSOR_SANDBOX_MODE!r})"
        )
    return updated, record


def configure_cursor_unattended_posture(
    *,
    config_path: Optional[Path] = None,
    stream=None,
) -> List[str]:
    """Set Cursor's approval and sandbox keys; return what it reports.

    An empty list means nothing to say: Cursor is absent, or already
    unattended.
    """
    target = config_path if config_path is not None else cursor_config_path()
    out = stream if stream is not None else sys.stdout
    config = _load(target)
    if config is None:
        return []
    updated, record = plan(config)
    actions: List[str] = []
    if record["set_keys"]:
        tmp = target.with_suffix(target.suffix + ".yoke-tmp")
        try:
            tmp.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
            os.replace(str(tmp), str(target))
        except OSError as exc:
            out.write(f"Could not write Cursor config at {target}: {exc}\n")
            return [f"cursor: {target} could not be updated ({exc})"]
        actions.append(
            f"cursor: enabled unattended mode in {target} "
            f"({', '.join(record['set_keys'])})"
        )
    for conflict in record["conflicts"]:
        actions.append(
            f"cursor: left your own setting in place — {conflict}; "
            "Cursor will keep asking until you change it"
        )
    for line in actions:
        out.write(f"{line}\n")
    return actions


__all__ = ["configure_cursor_unattended_posture", "plan"]

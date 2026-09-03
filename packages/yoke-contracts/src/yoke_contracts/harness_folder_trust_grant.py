"""Answer every harness's folder-trust prompt for one checkout or lane.

Approval posture is machine-wide and written once by the launcher install;
folder trust is per path, so it is written wherever Yoke starts working in a
new one — the checkout at project install, each linked worktree at lane
creation. Path-keyed with no inheritance in any of the three harnesses, so a
lane gets its own entry rather than relying on the checkout's.

Each grant is idempotent and additive: an existing entry is left alone, an
unrelated key is never touched, and a harness that is not set up on this
machine is skipped rather than created. Nothing here raises — a machine
whose harness state is unwritable still installs, and the report says which
prompt will still appear.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_contracts.harness_folder_trust import (
    CLAUDE_PROJECTS_KEY,
    CLAUDE_TRUST_KEY,
    claude_state_path,
    cursor_trust_file,
    trust_key,
)
from yoke_contracts.session_control.launch_permission_bypass import (
    CODEX_APPROVAL_POLICY,
)


def grant_folder_trust(
    checkout: str | Path,
    *,
    claude_state: Optional[Path] = None,
    codex_config: Optional[Path] = None,
    cursor_file: Optional[Path] = None,
) -> List[str]:
    """Trust *checkout* in every harness present; return what it granted.

    An empty list means every harness that is set up here already trusts the
    path, or none is set up at all.
    """
    path = trust_key(checkout)
    granted: List[str] = []
    granted.extend(_grant_claude(path, claude_state))
    granted.extend(_grant_codex(path, codex_config))
    granted.extend(_grant_cursor(path, cursor_file))
    return granted


def _grant_claude(path: str, state_path: Optional[Path]) -> List[str]:
    target = state_path if state_path is not None else claude_state_path()
    if not target.is_file():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"claude-code: {target} could not be read ({exc})"]
    if not isinstance(payload, dict):
        return [f"claude-code: {target} is not a JSON object"]
    projects = payload.get(CLAUDE_PROJECTS_KEY)
    if not isinstance(projects, dict):
        projects = {}
        payload[CLAUDE_PROJECTS_KEY] = projects
    entry = projects.get(path)
    entry = entry if isinstance(entry, dict) else {}
    if entry.get(CLAUDE_TRUST_KEY) is True:
        return []
    entry[CLAUDE_TRUST_KEY] = True
    projects[path] = entry
    try:
        _write_json(target, payload)
    except OSError as exc:
        return [f"claude-code: {target} could not be updated ({exc})"]
    return [f"claude-code: trusted {path}"]


def _grant_codex(path: str, config_path: Optional[Path]) -> List[str]:
    from yoke_contracts.harness_unattended_posture import codex_config_path
    from yoke_contracts.codex_config_posture import (
        CodexConfigUnreadable,
        changed,
        plan,
        read_config_text,
    )

    target = config_path if config_path is not None else codex_config_path()
    text = read_config_text(target)
    if text is None:
        return []
    try:
        # The same pass that writes Codex's approval posture also owns its
        # trust table, so trusting a path reuses it rather than re-deriving
        # the TOML surgery. Posture keys already present are left untouched.
        updated, record = plan(text, path)
    except CodexConfigUnreadable as exc:
        return [f"codex: {target} is not valid TOML ({exc})"]
    if not changed(record) or not record["trusted_checkout"]:
        return []
    try:
        target.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return [f"codex: {target} could not be updated ({exc})"]
    granted = [f"codex: trusted {path}"]
    if record["set_keys"]:
        granted.append(
            f"codex: also set {', '.join(record['set_keys'])} "
            f"(approval policy {CODEX_APPROVAL_POLICY!r})"
        )
    return granted


def _grant_cursor(path: str, trust_file: Optional[Path]) -> List[str]:
    target = trust_file if trust_file is not None else cursor_trust_file(path)
    if not target.parent.parent.is_dir():
        return []
    if target.is_file():
        return []
    payload: Dict[str, Any] = {
        "trustedAt": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "workspacePath": path,
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_json(target, payload)
    except OSError as exc:
        return [f"cursor: {target} could not be written ({exc})"]
    return [f"cursor: trusted {path}"]


def _write_json(target: Path, payload: Any) -> None:
    """Replace *target* atomically so a crash cannot truncate harness state."""
    tmp = target.with_suffix(target.suffix + ".yoke-tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


__all__ = ["grant_folder_trust"]

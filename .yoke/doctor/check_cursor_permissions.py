"""HCs covering the Cursor gates that decide whether commands run unprompted.

Cursor stacks three approval layers, and only the first two are project
files Yoke can install:

* ``HC-cursor-permission-config`` — ``.cursor/cli.json`` carries a
  non-empty ``permissions.allow`` (an allow-less deny-only file aborts
  every run before the agent starts) and ``.cursor/sandbox.json`` allows
  the control-plane origins this machine is configured against.
* ``HC-cursor-approval-posture`` — the machine-level Cursor settings,
  which no project install can reach, are not in the prompt-prone shape.
  This one always names the exact settings to change rather than only
  reporting that something is off.

Both files must be regular files: Cursor refuses project config paths
containing symlinks, exactly as it does for the hook config.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_contracts.cursor_permissions import (
    CURSOR_CLI_ALLOW,
    CURSOR_CLI_REL,
    CURSOR_SANDBOX_REL,
    control_plane_origins,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)

# Machine-level Cursor CLI config. Settings-level approval mode lives in
# Cursor's own preferences and cannot be installed from a project repo, so
# the check reads what it can and teaches the rest.
_USER_CLI_CONFIG = Path("~/.cursor/cli-config.json")

# The zero-prompt posture Yoke recommends, stated as the operator actions
# that produce it. Kept as prose (not a config write) because these knobs
# are machine-level and operator-owned.
POSTURE_REMEDIATION = (
    "Recommended Yoke posture for Cursor — set these in Cursor's own "
    "settings (Approvals / Execution mode):\n"
    "  1. Execution mode: Run Everything (parity with the maximum-bypass "
    "posture Yoke machines already run for other harnesses).\n"
    "  2. If you keep Auto-review instead, add `yoke *`, `git *`, and "
    "`gh *` to the command allowlist and set network mode to allow the "
    "origins in .cursor/sandbox.json.\n"
    "  3. Do not clear ~/.cursor/cli-config.json permissions.deny entries "
    "you authored deliberately — they still apply.\n"
    "Yoke's PreToolUse hook chain remains the enforcement layer in every "
    "mode; a hook deny holds even under --force."
)


def _root() -> Path:
    root = _resolve_repo_root()
    return Path(root) if root else Path(".")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _config_problems(root: Path, rel: str) -> List[str]:
    """Shape problems that make a Cursor config file unusable."""
    target = root / rel
    if target.is_symlink():
        return [
            f"{rel} is a symlink; Cursor refuses project config paths "
            "containing symlinks"
        ]
    if not target.is_file():
        return [
            f"{rel} is missing; run `yoke project install` (or `yoke dev "
            "setup` in the Yoke checkout) to install it"
        ]
    try:
        payload = _read_json(target)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{rel} is unreadable or invalid JSON: {exc}"]
    if not isinstance(payload, dict):
        return [f"{rel} must contain a JSON object"]
    return []


def _cli_allow_problems(root: Path) -> List[str]:
    problems = _config_problems(root, CURSOR_CLI_REL)
    if problems:
        return problems
    payload = _read_json(root / CURSOR_CLI_REL)
    permissions = payload.get("permissions")
    allow = permissions.get("allow") if isinstance(permissions, dict) else None
    if not isinstance(allow, list) or not allow:
        return [
            f"{CURSOR_CLI_REL} has no non-empty permissions.allow; Cursor "
            "aborts every run before the agent starts on an allow-less file"
        ]
    missing = [entry for entry in CURSOR_CLI_ALLOW if entry not in allow]
    if missing:
        return [
            f"{CURSOR_CLI_REL} permissions.allow is missing "
            + ", ".join(missing)
        ]
    return []


def _sandbox_origin_problems(root: Path) -> List[str]:
    problems = _config_problems(root, CURSOR_SANDBOX_REL)
    if problems:
        return problems
    payload = _read_json(root / CURSOR_SANDBOX_REL)
    policy = payload.get("networkPolicy")
    allow = policy.get("allow") if isinstance(policy, dict) else None
    if not isinstance(allow, list):
        return [f"{CURSOR_SANDBOX_REL} has no networkPolicy.allow list"]
    expected = control_plane_origins()
    if not expected:
        return [
            f"{CURSOR_SANDBOX_REL} cannot be verified: this machine declares "
            "no https control-plane or GitHub endpoint to allow"
        ]
    missing = [origin for origin in expected if origin not in allow]
    if missing:
        return [
            f"{CURSOR_SANDBOX_REL} networkPolicy.allow is missing "
            + ", ".join(missing)
            + "; sandboxed yoke commands will fail against the control plane"
        ]
    return []


def hc_cursor_permission_config(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    name = "cursor-permission-config"
    desc = "Cursor project permission and network config let yoke run unprompted"
    root = _root()
    problems = _cli_allow_problems(root) + _sandbox_origin_problems(root)
    if problems:
        rec.record(
            name, desc, "FAIL",
            "; ".join(problems)
            + "\nRepair: `yoke project install` (external project) or "
            "`yoke dev setup` (Yoke checkout) reapplies the managed regions "
            "without touching your own entries.",
        )
        return
    rec.record(
        name, desc, "PASS",
        f"{CURSOR_CLI_REL} allows the Yoke command family and "
        f"{CURSOR_SANDBOX_REL} allows every configured control-plane origin",
    )


def _user_cli_config() -> Optional[Dict[str, Any]]:
    path = _USER_CLI_CONFIG.expanduser()
    if not path.is_file():
        return None
    try:
        payload = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def hc_cursor_approval_posture(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    name = "cursor-approval-posture"
    desc = "Machine-level Cursor approval settings match the zero-prompt posture"
    payload = _user_cli_config()
    if payload is None:
        rec.record(
            name, desc, "WARN",
            f"{_USER_CLI_CONFIG} is absent or unreadable, so the machine-level "
            "approval posture cannot be confirmed.\n" + POSTURE_REMEDIATION,
        )
        return
    permissions = payload.get("permissions")
    permissions = permissions if isinstance(permissions, dict) else {}
    allow = permissions.get("allow")
    allow = allow if isinstance(allow, list) else []
    deny = permissions.get("deny")
    deny = deny if isinstance(deny, list) else []
    findings: List[str] = []
    if not any(str(entry).startswith("Shell(yoke") for entry in allow):
        findings.append(
            f"{_USER_CLI_CONFIG} permissions.allow does not allow the yoke "
            "command family, so an Auto-review session prompts on every call"
        )
    if deny:
        findings.append(
            f"{_USER_CLI_CONFIG} permissions.deny carries {len(deny)} entry(s); "
            "confirm none of them cover the yoke, git, or gh families"
        )
    if findings:
        rec.record(
            name, desc, "WARN",
            "; ".join(findings) + "\n" + POSTURE_REMEDIATION,
        )
        return
    rec.record(
        name, desc, "PASS",
        f"{_USER_CLI_CONFIG} allows the yoke command family with no deny "
        "entries to reconcile",
    )


from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        "cursor-permission-config",
        "Cursor project permission and network config let yoke run unprompted",
        hc_cursor_permission_config,
    ),
    (
        "cursor-approval-posture",
        "Machine-level Cursor approval settings match the zero-prompt posture",
        hc_cursor_approval_posture,
    ),
)


__all__ = [
    "POSTURE_REMEDIATION",
    "PROJECT_HEALTH_CHECKS",
    "hc_cursor_approval_posture",
    "hc_cursor_permission_config",
]

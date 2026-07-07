"""Python owner for on-bash-complete.sh logic.

Provides the business logic for PostToolUse/Bash hooks:
- Stray DB detection (shared with sqlite3_error_hook)
- Yoke script failure logging
- Dispatch progress sync

The shell script remains as the process-entry launcher.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Yoke script failure detection
# ---------------------------------------------------------------------------


def detect_script_failure(command: str, output: str) -> Optional[str]:
    """Detect when a Yoke script exits non-zero.

    Returns the formatted error log entry, or None if no failure detected.
    """
    # Only check Yoke scripts
    if ".agents/skills/yoke/scripts/" not in command and ".claude/skills/yoke/scripts/" not in command:
        return None

    # Check for exit code indicators
    if not re.search(r"Exit code [1-9]", output):
        return None

    exit_match = re.search(r"Exit code ([0-9]+)", output)
    exit_code = exit_match.group(1) if exit_match else "unknown"

    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    first_lines = "\n".join(output.splitlines()[:5])

    return f"{ts} | {command} | exit_code={exit_code}\n{first_lines}\n---"


def log_script_failure(
    project_root: str,
    command: str,
    output: str,
) -> None:
    """Log a Yoke script failure to ouroboros/errors.log."""
    entry = detect_script_failure(command, output)
    if not entry:
        return

    log_dir = os.path.join(project_root, "runtime", "ouroboros")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "errors.log")

    try:
        with open(log_path, "a") as f:
            f.write(entry + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Dispatch progress sync
# ---------------------------------------------------------------------------


def sync_dispatch_progress(
    project_root: str,
    script_dir: str,
    db_path: str,
    agent_dir: str,
) -> None:
    """Sync progress notes for the implementing dispatch task.

    Queries epic_dispatch_chains for the current task scoped to this agent's
    worktree, then syncs progress notes if the task is implementing.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import connect

    if not agent_dir:
        return
    try:
        conn = connect(db_path or None)
        chains = conn.execute(
            "SELECT epic_id, COALESCE(worktree_path, ''), COALESCE(current_task, '') "
            "FROM epic_dispatch_chains"
        ).fetchall()
        conn.close()
    except db_backend.operational_error_types():
        return

    for epic_id, chain_worktree, current_task in chains:
        if not current_task:
            continue

        # Scope to this agent's worktree
        if agent_dir and chain_worktree and chain_worktree != agent_dir:
            continue

        # Get task status via the Python db_router.
        try:
            r = subprocess.run(
                [sys.executable, "-m", "yoke_core.cli.db_router",
                 "epic", "task-get", str(epic_id), str(current_task)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0:
                continue
            parts = r.stdout.strip().split("|")
            if len(parts) < 8:
                continue
            current_status = parts[7]
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue

        if current_status == "implementing":
            try:
                import io
                from yoke_core.domain.epic_task_sync import sync_progress_notes

                sync_progress_notes(
                    str(epic_id),
                    str(current_task),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
            except Exception:
                pass
            break


def extract_hook_command(payload_json: str) -> str:
    """Extract the Bash command string from a PostToolUse payload."""
    try:
        data = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    tool_input = data.get("tool_input", {})
    if isinstance(tool_input, dict):
        return str(tool_input.get("command", ""))
    return ""


def extract_hook_output(payload_json: str) -> str:
    """Extract the text response from a PostToolUse payload."""
    try:
        data = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return ""

    response = data.get("tool_response", {})
    if isinstance(response, dict):
        content = response.get("content", "")
        if isinstance(content, list):
            return " ".join(
                str(c.get("text", "")) if isinstance(c, dict) else str(c)
                for c in content
            )[:500]
        return str(content)[:500]
    return str(response)[:500]


def run_hook(payload_json: str, *, script_dir: str = "", agent_dir: str = "") -> None:
    """Entry point for on-bash-complete.sh."""
    if not payload_json:
        return
    try:
        from yoke_core.domain.db_error_hook import detect_stray_db
        from runtime.harness.hook_helpers import find_project_root, resolve_yoke_db

        project_root = find_project_root()
        command = extract_hook_command(payload_json)
        output = extract_hook_output(payload_json)

        if project_root:
            detect_stray_db(project_root, command or "???")
            log_script_failure(project_root, command, output)

        db_path = resolve_yoke_db()
        if not db_path or not os.path.isfile(db_path):
            return

        if not script_dir:
            script_dir = os.environ.get("YOKE_SCRIPT_DIR", "")
        if not script_dir and project_root:
            script_dir = os.path.join(project_root, ".agents", "skills", "yoke", "scripts")
        if not agent_dir:
            agent_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")

        sync_dispatch_progress(project_root, script_dir, db_path, agent_dir)
    except Exception:
        return


def main() -> None:
    """CLI entry point for the Bash PostToolUse hook."""
    import sys

    payload = sys.stdin.read()
    run_hook(
        payload,
        script_dir=os.environ.get("YOKE_SCRIPT_DIR", ""),
        agent_dir=os.environ.get("CLAUDE_PROJECT_DIR", ""),
    )


if __name__ == "__main__":
    main()
